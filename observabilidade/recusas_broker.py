"""Recusas de conexão no broker, lidas do log do Mosquitto.

O broker não publica em tópico nenhum quem ele recusou: isso só aparece no log.
O Mosquitto grava o log também em .local/mosquitto/mosquitto.log
(broker/mosquitto.conf), e aqui ele é acompanhado, só para leitura.

Entram as conexões recusadas na autenticação (usuário inexistente ou senha
errada) e as que não falam MQTT sobre TLS. Publicação ou assinatura negada pela
ACL não aparece: o Mosquitto só a registra no nível debug, que não está ligado.
"""

import os
import re
import threading
import time
from collections import Counter, deque
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO = Path(os.getenv("BROKER_LOG", RAIZ / ".local" / "mosquitto" / "mosquitto.log"))
LER_DO_FIM_BYTES = 256 * 1024  # ao subir, recupera as recusas recentes sem ler o log inteiro
INTERVALO_SEGUNDOS = 1

PADROES = (
    (re.compile(r"^(\d+): Client (\S+) \[([^\]]+)\] disconnected: not authorised"), "credencial-recusada"),
    (re.compile(r"^(\d+): Client (\S+) \[([^\]]+)\] disconnected: Protocol error"), "sem-tls-ou-protocolo"),
)

_trava = threading.Lock()
recusas = deque(maxlen=2000)


def interpretar(linha):
    """A recusa descrita numa linha do log, ou None."""
    for padrao, motivo in PADROES:
        achado = padrao.match(linha)
        if achado:
            momento, cliente, endereco = achado.groups()
            # Sem identificação, o Mosquitto mostra o endereço no lugar do cliente.
            usuario = None if endereco.startswith(cliente + ":") else cliente
            return {"momento": datetime.fromtimestamp(int(momento)).astimezone(),
                    "motivo": motivo, "usuario": usuario, "endereco": endereco}
    return None


def registrar_linhas(linhas):
    novas = [r for r in map(interpretar, linhas) if r]
    with _trava:
        recusas.extend(novas)
    return novas


def situacao(agora=None, minutos=60):
    agora = agora or datetime.now().astimezone()
    desde = agora - timedelta(minutes=minutos)
    with _trava:
        recentes = [r for r in recusas if r["momento"] > desde]
        ultimas = list(recusas)[-20:]
    return {
        "logDisponivel": ARQUIVO.exists(),
        "minutos": minutos,
        "total": len(recentes),
        "porMotivo": dict(Counter(r["motivo"] for r in recentes)),
        "porUsuario": dict(Counter(r["usuario"] for r in recentes if r["usuario"])),
        "recentes": ultimas[::-1],
    }


def acompanhar(arquivo=ARQUIVO, parar=None):
    """Lê as linhas novas do log enquanto o processo roda; tolera o arquivo sumir ou ser truncado."""
    posicao, inode, resto = None, None, b""
    while not (parar and parar.is_set()):
        try:
            estado = arquivo.stat()
            if inode != estado.st_ino or posicao is None or estado.st_size < posicao:
                # Primeira leitura, arquivo novo ou truncado: recomeça perto do fim.
                posicao = 0 if inode is not None else max(0, estado.st_size - LER_DO_FIM_BYTES)
                inode, resto = estado.st_ino, b""
                pular_parcial = posicao > 0
            else:
                pular_parcial = False
            if estado.st_size > posicao:
                with arquivo.open("rb") as entrada:
                    entrada.seek(posicao)
                    bloco = entrada.read(estado.st_size - posicao)
                posicao += len(bloco)
                linhas = (resto + bloco).split(b"\n")
                resto = linhas.pop()
                if pular_parcial and linhas:
                    linhas.pop(0)
                registrar_linhas(linha.decode("utf-8", "replace") for linha in linhas)
        except FileNotFoundError:
            posicao, inode, resto = None, None, b""
        except OSError as erro:
            print(f"Falha ao ler o log do broker: {erro}")
        time.sleep(INTERVALO_SEGUNDOS)


def iniciar():
    threading.Thread(target=acompanhar, daemon=True, name="recusas-broker").start()
