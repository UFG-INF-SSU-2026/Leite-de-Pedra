"""Rotas do dashboard de admin (/admin): a permissão de admin sobre tudo e a gestão.

O ao vivo e o histórico operacional vêm da observabilidade, repassados depois
de conferir o admin. A gestão (usuários, ingressos, auditoria e fotos) usa o
papel painel do banco, que não lê senhas e só escreve o papel dos usuários, o
cancelamento de ingressos e a auditoria. Toda mudança e toda foto aberta ficam
registradas em auditoria.
"""

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Literal

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update

from modelos import Auditoria, Ingresso, Movimento, Usuario

from . import servicos
from .autenticacao import sessao_de_admin
from .servicos import BUCKET_FOTOS, s3, sessao_painel

VALIDADE_LINK_FOTO_SEGUNDOS = 300

rotas = APIRouter(prefix="/admin", dependencies=[Depends(sessao_de_admin)])

Limite = Query(100, ge=1, le=500)
Deslocamento = Query(0, ge=0)


def pagina(s, consulta, limite, deslocamento, converter):
    total = s.scalar(select(func.count()).select_from(consulta.order_by(None).subquery()))
    linhas = s.execute(consulta.limit(limite).offset(deslocamento)).all()
    return {"total": total, "itens": [converter(linha) for linha in linhas]}


def auditar(s, admin_id, acao, alvo, detalhe=None):
    s.add(Auditoria(admin_id=admin_id, acao=acao, alvo=alvo, detalhe=detalhe))


def usuario_json(u):
    return {"usuarioId": u.usuario_id, "login": u.login, "nome": u.nome, "papel": u.papel,
            "faceId": u.face_id, "criadoEm": u.criado_em}


def ingresso_json(i, dono=None):
    situacao = ("cancelado" if i.cancelado_em else "usado" if i.usado_em else "disponivel")
    return {"ingressoId": i.ingresso_id, "usuarioId": i.usuario_id, "dono": dono,
            "situacao": situacao, "emitidoEm": i.emitido_em, "usadoEm": i.usado_em,
            "filaEntrada": i.fila_entrada, "leituraId": i.leitura_id,
            "validadorId": i.validador_id, "canceladoEm": i.cancelado_em}


# Colunas de usuarios que o papel painel pode ler (nunca senha_hash).
COLUNAS_USUARIO = (Usuario.usuario_id, Usuario.login, Usuario.nome, Usuario.papel,
                   Usuario.face_id, Usuario.criado_em)


# ---------- visão geral ----------

def da_observabilidade(caminho, request):
    """GET na observabilidade com a mesma consulta; aqui só se aplica a permissão de admin."""
    url = f"{servicos.URL_OBSERVABILIDADE}/{caminho}"
    if request.url.query:
        url += f"?{request.url.query}"
    try:
        with urllib.request.urlopen(url, timeout=3) as resposta:
            return json.load(resposta)
    except urllib.error.HTTPError as erro:  # 422 de parâmetro inválido, por exemplo
        with erro:
            raise HTTPException(erro.code, json.load(erro).get("detail"))
    except OSError:
        raise HTTPException(503, "Observabilidade fora do ar: o ao vivo e o histórico estão indisponíveis.")


def _repassar(caminho):
    def rota(request: Request):
        return da_observabilidade(caminho, request)
    return rota


# Ao vivo e histórico operacional: da observabilidade, que lê o broker e o banco.
for _caminho in ("ao-vivo", "historico", "movimentos", "estados"):
    rotas.add_api_route(f"/{_caminho}", _repassar(_caminho), methods=["GET"])


@rotas.get("/leituras")
def leituras(request: Request):
    """Leituras da observabilidade com quem passou: o dono do ingresso e o login do validador.

    A observabilidade não lê dados pessoais; eles vêm daqui, com o papel painel.
    """
    dados = da_observabilidade("leituras", request)
    ingressos = {i["ingressoId"] for i in dados["itens"] if i["ingressoId"]}
    validadores = {i["validadorId"] for i in dados["itens"] if i["validadorId"]}
    with sessao_painel() as s:
        donos = {ingresso_id: {"nome": nome, "login": login} for ingresso_id, nome, login in s.execute(
            select(Ingresso.ingresso_id, Usuario.nome, Usuario.login)
            .join(Usuario, Usuario.usuario_id == Ingresso.usuario_id)
            .where(Ingresso.ingresso_id.in_(ingressos)))}
        logins = dict(s.execute(select(Usuario.usuario_id, Usuario.login)
                                .where(Usuario.usuario_id.in_(validadores))).all())
    for item in dados["itens"]:
        item["dono"] = donos.get(item["ingressoId"])
        item["validadorLogin"] = logins.get(item["validadorId"])
    return dados


@rotas.get("/resumo")
def resumo(request: Request):
    with sessao_painel() as s:
        papeis = dict(s.execute(select(Usuario.papel, func.count()).group_by(Usuario.papel)).all())
        ingressos = s.execute(select(
            func.count(),
            func.count(Ingresso.usado_em),
            func.count(Ingresso.cancelado_em),
        )).one()
    return {
        **da_observabilidade("resumo", request),
        "usuarios": {papel: papeis.get(papel, 0) for papel in ("cliente", "validador", "admin")},
        "ingressos": {"emitidos": ingressos[0], "usados": ingressos[1], "cancelados": ingressos[2],
                      "disponiveis": ingressos[0] - ingressos[1] - ingressos[2]},
    }


# ---------- usuários ----------

@rotas.get("/usuarios")
def usuarios(busca: str | None = Query(None, max_length=80),
             papel: Literal["cliente", "validador", "admin"] | None = None,
             limite: int = Limite, deslocamento: int = Deslocamento):
    consulta = select(*COLUNAS_USUARIO).order_by(Usuario.criado_em.desc())
    if busca:
        padrao = f"%{busca}%"
        consulta = consulta.where(or_(Usuario.login.ilike(padrao), Usuario.nome.ilike(padrao),
                                      Usuario.usuario_id == busca))
    if papel:
        consulta = consulta.where(Usuario.papel == papel)
    with sessao_painel() as s:
        return pagina(s, consulta, limite, deslocamento, usuario_json)


class NovoPapel(BaseModel):
    papel: Literal["cliente", "validador", "admin"]


@rotas.put("/usuarios/{usuario_id}/papel")
def mudar_papel(usuario_id: str, dados: NovoPapel, admin=Depends(sessao_de_admin)):
    if usuario_id == admin["sub"]:
        raise HTTPException(409, "Você não pode mudar o próprio papel.")
    with sessao_painel.begin() as s:
        anterior = s.scalar(select(Usuario.papel).where(Usuario.usuario_id == usuario_id)
                            .with_for_update())
        if anterior is None:
            raise HTTPException(404, "Usuário não encontrado.")
        if anterior != dados.papel:
            s.execute(update(Usuario).where(Usuario.usuario_id == usuario_id)
                      .values(papel=dados.papel))
            auditar(s, admin["sub"], "mudar-papel", usuario_id, f"{anterior} -> {dados.papel}")
    return {"usuarioId": usuario_id, "papel": dados.papel}


# ---------- ingressos ----------

@rotas.get("/ingressos")
def ingressos(usuario: str | None = Query(None, max_length=64),
              situacao: Literal["disponivel", "usado", "cancelado"] | None = None,
              busca: str | None = Query(None, max_length=64),
              limite: int = Limite, deslocamento: int = Deslocamento):
    consulta = (select(Ingresso, Usuario.login)
                .join(Usuario, Usuario.usuario_id == Ingresso.usuario_id)
                .order_by(Ingresso.emitido_em.desc()))
    if usuario:
        consulta = consulta.where(Ingresso.usuario_id == usuario)
    if busca:
        consulta = consulta.where(Ingresso.ingresso_id.ilike(f"%{busca}%"))
    if situacao == "cancelado":
        consulta = consulta.where(Ingresso.cancelado_em.is_not(None))
    elif situacao == "usado":
        consulta = consulta.where(Ingresso.usado_em.is_not(None))
    elif situacao == "disponivel":
        consulta = consulta.where(Ingresso.usado_em.is_(None), Ingresso.cancelado_em.is_(None))
    with sessao_painel() as s:
        return pagina(s, consulta, limite, deslocamento, lambda r: ingresso_json(r[0], r[1]))


class Cancelamento(BaseModel):
    motivo: str = Field(min_length=3, max_length=200)


@rotas.post("/ingressos/{ingresso_id}/cancelar")
def cancelar(ingresso_id: str, dados: Cancelamento, admin=Depends(sessao_de_admin)):
    with sessao_painel.begin() as s:
        # Trava a linha: o processador não marca a entrada enquanto o admin cancela.
        ingresso = s.get(Ingresso, ingresso_id, with_for_update=True)
        if ingresso is None:
            raise HTTPException(404, "Ingresso não encontrado.")
        if ingresso.usado_em or ingresso.cancelado_em:
            raise HTTPException(409, "Só um ingresso disponível pode ser cancelado.")
        ingresso.cancelado_em = datetime.now(timezone.utc)
        auditar(s, admin["sub"], "cancelar-ingresso", ingresso_id, dados.motivo)
    return ingresso_json(ingresso)


# ---------- foto de uma leitura ----------

@rotas.post("/leituras/{evento_id}/foto")
def foto_da_leitura(evento_id: str, admin=Depends(sessao_de_admin)):
    """Link temporário para a foto da leitura (o bucket apaga as fotos em 1 dia)."""
    chave = f"leituras/{evento_id}.jpg"
    with sessao_painel() as s:
        existe = s.scalar(select(Movimento.evento_id).where(Movimento.evento_id == evento_id,
                                                             Movimento.tipo == "resultado"))
    if not existe:
        raise HTTPException(404, "Leitura não encontrada.")
    try:
        s3.head_object(Bucket=BUCKET_FOTOS, Key=chave)
    except ClientError:
        raise HTTPException(404, "A foto já foi apagada do bucket.")
    with sessao_painel.begin() as s:
        auditar(s, admin["sub"], "ver-foto", evento_id)
    url = s3.generate_presigned_url("get_object", Params={"Bucket": BUCKET_FOTOS, "Key": chave},
                                    ExpiresIn=VALIDADE_LINK_FOTO_SEGUNDOS)
    return {"url": url, "expiraEmSegundos": VALIDADE_LINK_FOTO_SEGUNDOS}


@rotas.get("/auditoria")
def auditoria(limite: int = Limite, deslocamento: int = Deslocamento):
    consulta = (select(Auditoria, Usuario.login)
                .join(Usuario, Usuario.usuario_id == Auditoria.admin_id)
                .order_by(Auditoria.momento.desc()))
    with sessao_painel() as s:
        return pagina(s, consulta, limite, deslocamento, lambda r: {
            "momento": r[0].momento, "admin": r[1], "acao": r[0].acao, "alvo": r[0].alvo,
            "detalhe": r[0].detalhe})
