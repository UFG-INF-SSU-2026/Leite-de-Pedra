import time

import jwt

from .configuracao import ARQUIVO_CHAVE_JWT, DURACAO_SESSAO_SEGUNDOS, NOME_COOKIE

ATRIBUTOS_COOKIE = "Path=/; HttpOnly; Secure; SameSite=Strict"


def ler_chave_jwt():
    return ARQUIVO_CHAVE_JWT.read_text(encoding="utf-8").strip()


def emitir_token(usuario, chave, agora=None):
    agora = int(agora or time.time())
    return jwt.encode({"sub": usuario, "iat": agora, "exp": agora + DURACAO_SESSAO_SEGUNDOS},
                      chave, algorithm="HS256")


def usuario_do_token(token, chave):
    try:
        dados = jwt.decode(token, chave, algorithms=["HS256"],
                           options={"require": ["sub", "exp", "iat"]})
    except jwt.InvalidTokenError:
        return None
    return dados["sub"]


def cookie_de_sessao(token):
    return f"{NOME_COOKIE}={token}; Max-Age={DURACAO_SESSAO_SEGUNDOS}; {ATRIBUTOS_COOKIE}"


def cookie_de_saida():
    return f"{NOME_COOKIE}=; Max-Age=0; {ATRIBUTOS_COOKIE}"
