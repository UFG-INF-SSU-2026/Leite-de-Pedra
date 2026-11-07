"""Sessão por token (JWT HS256 no cabeçalho Authorization) e exigência de papel."""

import time

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from modelos import Usuario

from .servicos import PASTA_SEGREDOS, sessao_painel

DURACAO_TOKEN_SEGUNDOS = 8 * 3600  # um turno de validador

portador = HTTPBearer(auto_error=False)


def ler_chave_jwt():
    return (PASTA_SEGREDOS / "jwt.key").read_text(encoding="utf-8").strip()


def emitir_token(usuario_id, papel, chave, agora=None):
    agora = int(agora or time.time())
    return jwt.encode({"sub": usuario_id, "papel": papel, "iat": agora,
                       "exp": agora + DURACAO_TOKEN_SEGUNDOS}, chave, algorithm="HS256")


def sessao(request: Request, credencial: HTTPAuthorizationCredentials = Depends(portador)):
    if credencial is None:
        raise HTTPException(401, "Entre com login e senha.")
    try:
        return jwt.decode(credencial.credentials, request.app.state.chave_jwt, algorithms=["HS256"],
                          options={"require": ["sub", "papel", "exp", "iat"]})
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Sessão inválida ou expirada. Entre de novo.")


def sessao_de_validador(dados=Depends(sessao)):
    # O processador confere de novo o papel no banco a cada leitura.
    if dados["papel"] != "validador":
        raise HTTPException(403, "Só validadores leem ingressos na catraca.")
    return dados


def sessao_de_admin(dados=Depends(sessao)):
    # Confere no banco a cada requisição: um admin rebaixado perde o acesso na hora,
    # sem esperar o token expirar.
    if dados["papel"] == "admin":
        with sessao_painel() as s:
            papel = s.scalar(select(Usuario.papel).where(Usuario.usuario_id == dados["sub"]))
        if papel == "admin":
            return dados
    raise HTTPException(403, "Só administradores acessam o painel.")
