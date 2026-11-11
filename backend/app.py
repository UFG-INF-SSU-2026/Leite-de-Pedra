"""API HTTPS do backend: rotas do app mobile e do dashboard de admin.

App: clientes se cadastram com login, senha e uma foto do rosto e compram
ingressos; validadores leem o QR do ingresso e capturam o rosto. O backend
reconhece o rosto no Rekognition, guarda a foto no S3, publica a leitura no
MQTT com o id do validador e o usuário reconhecido e espera o resultado do
processador, que é quem decide se o ingresso vale. Nenhuma credencial da AWS ou
do MQTT vai para o celular. Dashboard: rotas /admin (admin.py) e a SPA em /painel.
"""

import base64
import json
import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from modelos import Ingresso, Usuario
from mqtt_config import conectar, desconectar, evento
from senhas import autenticar_hash, gerar_hash_senha

from . import admin
from .autenticacao import (DURACAO_TOKEN_SEGUNDOS, emitir_token, ler_chave_jwt, sessao,
                           sessao_de_validador)
from .servicos import (BUCKET_FOTOS, COLECAO_ROSTOS, RAIZ, cliente_mqtt, receber_resultado,  # noqa: F401
                       rekognition, respostas, s3, sessao_backend, trava_respostas)

# Semelhança mínima (%), no cadastro (um rosto, uma conta) e na catraca. Mais alto
# recusa mais gente parecida; mais baixo aceita fotos ruins. Ajustar com fotos reais do evento.
LIMIAR_SEMELHANCA = 95
TAMANHO_MAXIMO_CORPO = 8 * 1024 * 1024  # foto em base64 de até ~5 MB (limite do Rekognition)
ESPERA_RESULTADO_SEGUNDOS = 10
ATRASO_APOS_LOGIN_RECUSADO_SEGUNDOS = 1
PASTA_DASHBOARD = RAIZ / "admin" / "dist"  # build da SPA (cd admin && npm run build)

# A SPA só carrega o que é dela; as fotos das leituras vêm do S3 por URL pré-assinada.
CABECALHOS_DASHBOARD = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data: https://*.amazonaws.com; "
                               "style-src 'self'; script-src 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


@asynccontextmanager
async def ciclo_de_vida(app):
    app.state.chave_jwt = ler_chave_jwt()
    app.state.cliente_mqtt = cliente_mqtt
    conectar(cliente_mqtt, "backend", assincrono=True)
    cliente_mqtt.loop_start()
    yield
    desconectar(cliente_mqtt, "backend")
    cliente_mqtt.loop_stop()


app = FastAPI(title="Leite de Pedra", lifespan=ciclo_de_vida, docs_url=None, redoc_url=None)
app.include_router(admin.rotas)


@app.middleware("http")
async def limitar_corpo_e_proteger(request: Request, proximo):
    if int(request.headers.get("content-length") or 0) > TAMANHO_MAXIMO_CORPO:
        return JSONResponse({"detail": "Corpo grande demais."}, status_code=413)
    resposta = await proximo(request)
    resposta.headers["Cache-Control"] = "no-store"
    resposta.headers["Strict-Transport-Security"] = "max-age=31536000"
    if request.url.path.startswith("/painel"):
        resposta.headers.update(CABECALHOS_DASHBOARD)
    return resposta


if PASTA_DASHBOARD.is_dir():
    app.mount("/painel", StaticFiles(directory=PASTA_DASHBOARD, html=True), name="painel")


@app.get("/", include_in_schema=False)
def raiz():
    return RedirectResponse("/painel/")


def decodificar_foto(foto_base64):
    try:
        foto = base64.b64decode(foto_base64, validate=True)
    except ValueError:  # binascii.Error, ou caractere fora do ASCII
        raise HTTPException(422, "A foto precisa estar em base64.")
    if not foto.startswith((b"\xff\xd8", b"\x89PNG")):
        raise HTTPException(422, "A foto precisa ser JPEG ou PNG.")
    return foto


# ---------- rotas ----------

LOGIN = r"^[a-z0-9_.-]{3,32}$"
FOTO = Field(min_length=100, max_length=7_000_000)


class Cadastro(BaseModel):
    login: str = Field(pattern=LOGIN)
    senha: str = Field(min_length=10, max_length=256)
    nome: str = Field(min_length=1, max_length=80)
    foto: str = FOTO


class Credenciais(BaseModel):
    login: str = Field(max_length=32)
    senha: str = Field(max_length=256)


class Leitura(BaseModel):
    ingressoId: str = Field(pattern=r"^[A-F0-9]{12}$")
    filaId: str = Field(pattern=r"^fila-[a-z0-9-]{1,32}$")
    foto: str = FOTO


@app.post("/usuarios", status_code=201)
def cadastrar(dados: Cadastro):
    foto = {"Bytes": decodificar_foto(dados.foto)}
    with sessao_backend() as s:
        if s.scalar(select(Usuario.usuario_id).where(Usuario.login == dados.login)):
            raise HTTPException(409, "Este login já existe.")
    # Um rosto, uma conta: a catraca confere o rosto contra o dono do ingresso.
    try:
        existente = rekognition.search_faces_by_image(
            CollectionId=COLECAO_ROSTOS, Image=foto,
            FaceMatchThreshold=LIMIAR_SEMELHANCA, MaxFaces=1)["FaceMatches"]
    except rekognition.exceptions.InvalidParameterException:
        raise HTTPException(422, "Nenhum rosto encontrado na foto.")
    if existente:
        raise HTTPException(409, "Este rosto já tem uma conta.")

    usuario_id = uuid.uuid4().hex
    rostos = rekognition.index_faces(
        CollectionId=COLECAO_ROSTOS, Image=foto, ExternalImageId=usuario_id,
        MaxFaces=1, QualityFilter="AUTO")["FaceRecords"]
    if not rostos:
        raise HTTPException(422, "Rosto sem qualidade suficiente: tire a foto de frente e com boa luz.")
    face_id = rostos[0]["Face"]["FaceId"]
    try:
        # O papel fica no padrão do banco (cliente): o backend não tem permissão para escolhê-lo.
        with sessao_backend.begin() as s:
            s.add(Usuario(usuario_id=usuario_id, login=dados.login, nome=dados.nome,
                          senha_hash=gerar_hash_senha(dados.senha), face_id=face_id))
    except Exception as erro:
        # Sem a conta no banco, o rosto na coleção ficaria órfão.
        rekognition.delete_faces(CollectionId=COLECAO_ROSTOS, FaceIds=[face_id])
        if isinstance(erro, IntegrityError):
            raise HTTPException(409, "Este login já existe.")
        raise
    return {"usuarioId": usuario_id}


@app.post("/sessoes")
def entrar(dados: Credenciais, request: Request):
    with sessao_backend() as s:
        usuario = s.scalar(select(Usuario).where(Usuario.login == dados.login))
    if not autenticar_hash(dados.senha, usuario.senha_hash if usuario else None):
        time.sleep(ATRASO_APOS_LOGIN_RECUSADO_SEGUNDOS)
        raise HTTPException(401, "Login ou senha inválidos.")
    return {"token": emitir_token(usuario.usuario_id, usuario.papel, request.app.state.chave_jwt),
            "papel": usuario.papel, "expiraEmSegundos": DURACAO_TOKEN_SEGUNDOS}


@app.get("/eu")
def eu(dados=Depends(sessao)):
    with sessao_backend() as s:
        usuario = s.get(Usuario, dados["sub"])
    if usuario is None:
        raise HTTPException(401, "Conta não encontrada. Entre de novo.")
    return {"usuarioId": usuario.usuario_id, "login": usuario.login, "nome": usuario.nome,
            "papel": usuario.papel}


@app.post("/ingressos", status_code=201)
def comprar(dados=Depends(sessao)):
    # ponytail: compra sem pagamento nem limite por evento; um evento só, implícito.
    ingresso_id = uuid.uuid4().hex[:12].upper()
    # Só as duas colunas que o papel backend pode inserir: o ingresso nasce não usado.
    with sessao_backend.begin() as s:
        s.execute(insert(Ingresso).values(ingresso_id=ingresso_id, usuario_id=dados["sub"]))
    return {"ingressoId": ingresso_id}


@app.get("/ingressos")
def meus_ingressos(dados=Depends(sessao)):
    with sessao_backend() as s:
        ingressos = s.scalars(select(Ingresso).where(Ingresso.usuario_id == dados["sub"])
                              .order_by(Ingresso.emitido_em.desc())).all()
    return [{"ingressoId": i.ingresso_id, "emitidoEm": i.emitido_em, "usadoEm": i.usado_em,
             "filaEntrada": i.fila_entrada} for i in ingressos]


def reconhecer(foto):
    """(reconhecimento, usuario_id) do rosto na catraca; quem decide a entrada é o processador."""
    try:
        encontrados = rekognition.search_faces_by_image(
            CollectionId=COLECAO_ROSTOS, Image={"Bytes": foto},
            FaceMatchThreshold=LIMIAR_SEMELHANCA, MaxFaces=1)["FaceMatches"]
    except Exception as erro:
        # Sem rosto na foto ou sem resposta da AWS: vira "indeterminado", e o operador decide.
        print(f"Falha no reconhecimento: {erro}")
        return "falha", None
    usuario = encontrados[0]["Face"].get("ExternalImageId") if encontrados else None
    return ("reconhecido", usuario) if usuario else ("nao-reconhecido", None)


def apagar_foto(chave):
    """Leitura aceita: a foto não serve mais para revisão. Recusadas e indeterminadas
    ficam para o admin conferir até a regra do bucket apagá-las (1 dia)."""
    try:
        s3.delete_object(Bucket=BUCKET_FOTOS, Key=chave)
    except Exception as erro:
        # A entrada já foi decidida; a regra do bucket apaga a foto depois.
        print(f"Falha ao apagar {chave}: {erro}")


@app.post("/leituras")
def ler_na_catraca(dados: Leitura, validador=Depends(sessao_de_validador)):
    foto = decodificar_foto(dados.foto)
    if not cliente_mqtt.is_connected():
        raise HTTPException(503, "Sem conexão com o broker. Decida manualmente.")
    reconhecimento, usuario = reconhecer(foto)
    evento_id = uuid.uuid4().hex
    correlacao = uuid.uuid4().hex  # a operação: leitura, resultado e o que vier deles
    chave = f"leituras/{evento_id}.jpg"  # o bucket apaga leituras/ depois de 1 dia
    s3.put_object(Bucket=BUCKET_FOTOS, Key=chave, Body=foto, ContentType="image/jpeg")

    espera = [threading.Event(), None]
    with trava_respostas:
        respostas[correlacao] = espera
    try:
        # O processador confere de novo, no banco, se validadorId é mesmo validador, e
        # se o ingresso é de usuarioReconhecido. A ACL só deixa o backend publicar leituras.
        payload = {"filaId": dados.filaId, "fotoRef": chave, "ingressoId": dados.ingressoId,
                   "validadorId": validador["sub"], "reconhecimento": reconhecimento}
        if usuario:
            payload["usuarioReconhecido"] = usuario
        leitura = evento("leitura", "backend", payload, correlation_id=correlacao, event_id=evento_id)
        cliente_mqtt.publish(f"fila/{dados.filaId}/leitura", json.dumps(leitura), qos=1)
        if not espera[0].wait(ESPERA_RESULTADO_SEGUNDOS):
            raise HTTPException(504, "O processador não respondeu. Decida manualmente.")
    finally:
        with trava_respostas:
            respostas.pop(correlacao, None)
    resultado = espera[1]
    resposta = {"eventId": evento_id, "ingressoId": dados.ingressoId,
                "resultado": resultado["resultado"], "motivo": resultado.get("motivo")}
    if resultado["resultado"] == "aceito":
        apagar_foto(chave)
        # Aceito, o rosto reconhecido é o do dono do ingresso: o validador confere quem entrou.
        with sessao_backend() as s:
            pessoa = s.get(Usuario, usuario) if usuario else None
        if pessoa:
            resposta["pessoa"] = {"nome": pessoa.nome, "login": pessoa.login}
    return resposta
