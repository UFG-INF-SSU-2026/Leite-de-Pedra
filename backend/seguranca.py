"""Limite de tentativas de login e registro de logins recusados e acessos negados.

O limite fica em memória: o backend é um processo só, e reiniciá-lo zera a
contagem. A tentativa é contada antes de a senha ser conferida, para pedidos em
paralelo não passarem juntos pelo limite; o login certo a devolve.

O registro vai para eventos_seguranca, onde o papel backend só insere. Senha,
token e corpo do pedido nunca são gravados.
"""

import threading
import time
from collections import deque

from sqlalchemy import text

from .servicos import sessao_backend

JANELA_LOGIN_SEGUNDOS = 300
MAXIMO_POR_LOGIN = 5   # falhas do mesmo endereço no mesmo login, na janela
MAXIMO_POR_ENDERECO = 50  # falhas do mesmo endereço, somando os logins
# Registros por endereço por minuto: um ataque não enche o banco.
MAXIMO_REGISTROS_POR_MINUTO = 60

# SQL direto: o ORM pediria de volta o id gerado (ou a sequência), e o papel
# backend só pode inserir nesta tabela.
INSERIR = text("INSERT INTO eventos_seguranca (tipo, login, usuario_id, endereco, metodo, rota) "
               "VALUES (:tipo, :login, :usuario_id, :endereco, :metodo, :rota)")

TIPOS_POR_STATUS = {401: "nao-autenticado", 403: "acesso-negado", 429: "login-bloqueado"}


class Limitador:
    """No máximo `maximo` marcas por chave dentro da janela deslizante."""

    def __init__(self, janela):
        self.janela = janela
        self.marcas = {}
        self.trava = threading.Lock()

    def reservar(self, limites, agora=None):
        """limites: [(chave, maximo)]. Marca todas as chaves e devolve 0, ou não marca
        nenhuma e devolve em quantos segundos tentar de novo."""
        agora = time.monotonic() if agora is None else agora
        with self.trava:
            if len(self.marcas) > 10000:  # logins inventados não acumulam para sempre
                self.marcas = {c: m for c, m in self.marcas.items() if m and m[-1] > agora - self.janela}
            filas = []
            espera = 0
            for chave, maximo in limites:
                fila = self.marcas.setdefault(chave, deque())
                while fila and fila[0] <= agora - self.janela:
                    fila.popleft()
                if len(fila) >= maximo:
                    espera = max(espera, int(fila[0] + self.janela - agora) + 1)
                filas.append(fila)
            if not espera:
                for fila in filas:
                    fila.append(agora)
            return espera

    def esquecer(self, chave):
        with self.trava:
            self.marcas.pop(chave, None)

    def devolver(self, chave):
        """Retira a marca mais recente da chave (a tentativa que deu certo)."""
        with self.trava:
            if self.marcas.get(chave):
                self.marcas[chave].pop()

    def limpar(self):
        with self.trava:
            self.marcas.clear()


logins = Limitador(JANELA_LOGIN_SEGUNDOS)
registros = Limitador(60)


def reservar_login(endereco, login):
    return logins.reservar([((endereco, login), MAXIMO_POR_LOGIN), (endereco, MAXIMO_POR_ENDERECO)])


def login_aceito(endereco, login):
    logins.esquecer((endereco, login))
    logins.devolver(endereco)


def endereco_de(request):
    return request.client.host if request.client else "desconhecido"


def registrar_negado(request, status):
    """Grava a recusa. Uma falha ao gravar não muda a resposta ao cliente."""
    endereco = endereco_de(request)
    if registros.reservar([(endereco, MAXIMO_REGISTROS_POR_MINUTO)]):
        return
    login = getattr(request.state, "login_tentado", None)
    tipo = "login-recusado" if status == 401 and login is not None else TIPOS_POR_STATUS[status]
    try:
        with sessao_backend.begin() as s:
            s.execute(INSERIR, {"tipo": tipo, "login": login,
                                "usuario_id": getattr(request.state, "usuario_id", None),
                                "endereco": endereco, "metodo": request.method[:10],
                                "rota": request.url.path[:200]})
    except Exception as erro:
        print(f"Falha ao registrar {tipo}: {type(erro).__name__}")
