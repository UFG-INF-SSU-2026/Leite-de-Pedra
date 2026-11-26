"""Seed de desenvolvimento: um usuário de cada papel, todos com a senha 123.

    python3 banco/seed.py [--foto-cliente <foto.jpg>]

Cria `cliente` (com um ingresso disponível), `validador` e `admin`. Usa os
mesmos caminhos do sistema: o papel backend do banco cria as contas (que
nascem cliente) e o papel painel define o papel. Pode rodar de novo: o que já
existe fica como está.

Com --foto-cliente, o rosto do cliente vai para a coleção do Rekognition
(REKOGNITION_COLECAO, credencial AWS com IndexFaces), e ele passa de verdade
pela catraca. Sem a foto, e para validador e admin, o FaceId é fictício.

Senha conhecida: só para desenvolvimento, nunca num banco de evento real.
"""

import os
import sys
import uuid
from pathlib import Path

from sqlalchemy import insert, select, update

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from modelos import Ingresso, Usuario, criar_motor, fabrica_de_sessoes  # noqa: E402
from senhas import gerar_hash_senha  # noqa: E402

SENHA = "123"
USUARIOS = (("cliente", "Cliente Seed"), ("validador", "Validador Seed"), ("admin", "Admin Seed"))


def rosto_real(foto, usuario_id):
    import boto3
    colecao = os.getenv("REKOGNITION_COLECAO")
    if not colecao:
        sys.exit("Defina REKOGNITION_COLECAO para cadastrar o rosto do cliente.")
    rekognition = boto3.client("rekognition")
    imagem = {"Bytes": Path(foto).read_bytes()}
    existente = rekognition.search_faces_by_image(
        CollectionId=colecao, Image=imagem, FaceMatchThreshold=95, MaxFaces=1)["FaceMatches"]
    if existente:
        sys.exit(f"Este rosto já está na coleção (usuário {existente[0]['Face'].get('ExternalImageId')}).")
    rostos = rekognition.index_faces(CollectionId=colecao, Image=imagem, ExternalImageId=usuario_id,
                                     MaxFaces=1, QualityFilter="AUTO")["FaceRecords"]
    if not rostos:
        sys.exit("Nenhum rosto com qualidade suficiente na foto.")
    return rostos[0]["Face"]["FaceId"]


def main():
    argumentos = sys.argv[1:]
    if argumentos and (len(argumentos) != 2 or argumentos[0] != "--foto-cliente"):
        sys.exit(__doc__.strip().split("\n\n")[1])
    foto_cliente = argumentos[1] if argumentos else None

    backend = fabrica_de_sessoes(criar_motor("backend"))
    painel = fabrica_de_sessoes(criar_motor("painel"))
    hash_senha = gerar_hash_senha(SENHA)

    for papel, nome in USUARIOS:
        with backend() as s:
            usuario_id = s.scalar(select(Usuario.usuario_id).where(Usuario.login == papel))
        if usuario_id:
            print(f"{papel}: já existe ({usuario_id})")
        else:
            usuario_id = uuid.uuid4().hex
            face_id = (rosto_real(foto_cliente, usuario_id) if papel == "cliente" and foto_cliente
                       else f"seed-sem-rosto-{usuario_id}")
            with backend.begin() as s:
                s.add(Usuario(usuario_id=usuario_id, login=papel, nome=nome,
                              senha_hash=hash_senha, face_id=face_id))
            print(f"{papel}: criado ({usuario_id})")
        with painel.begin() as s:
            s.execute(update(Usuario).where(Usuario.usuario_id == usuario_id).values(papel=papel))

        if papel == "cliente":
            with backend() as s:
                disponivel = s.scalar(select(Ingresso.ingresso_id).where(
                    Ingresso.usuario_id == usuario_id, Ingresso.usado_em.is_(None),
                    Ingresso.cancelado_em.is_(None)))
            if not disponivel:
                disponivel = uuid.uuid4().hex[:12].upper()
                with backend.begin() as s:
                    s.execute(insert(Ingresso).values(ingresso_id=disponivel, usuario_id=usuario_id))
            print(f"cliente: ingresso disponível {disponivel}")

    print(f"Logins cliente, validador e admin, todos com a senha {SENHA}.")


if __name__ == "__main__":
    main()
