"""Situação ao vivo do sistema, montada com o que chega do broker.

A observabilidade assina todos os tópicos das filas, a presença de cada
componente (sistema/+/status) e o que o processador rejeitou
(sistema/+/rejeitado), e repassa cada mensagem a registrar_mensagem. Nada
daqui é gravado: o broker não guarda histórico, então isto é só o agora; o
histórico vem do banco, gravado pelo processador.
"""

import threading
from collections import Counter, deque
from datetime import datetime

from mqtt_config import ler_evento

TOPICOS = ("contagem", "saida", "heartbeat", "leitura", "resultado", "estado", "recomendacao", "reacao")
LIMITE_SEM_HEARTBEAT_SEGUNDOS = 8
QUANTIDADE_MENSAGENS_RECENTES = 100

_trava = threading.Lock()
filas_ao_vivo = {}
componentes = {}  # source -> {"online", "atualizadoEm"}, pelo status retido e pelo Last Will
rejeitadas = Counter()  # motivo -> quantas desde que a observabilidade subiu
mensagens_recentes = deque(maxlen=QUANTIDADE_MENSAGENS_RECENTES)


def agora_local():
    return datetime.now().astimezone()


def situacao_vazia():
    return {"estado": None, "recomendacao": None, "ultimo_heartbeat": None,
            "ultima_leitura": None, "ultimo_resultado": None, "ultima_reacao": None}


def registrar_mensagem(topico, conteudo, recebido_em=None):
    """Valida e guarda uma mensagem do broker; devolve a mensagem, ou None se for descartada."""
    recebido_em = recebido_em or agora_local()
    evento = ler_evento(topico, conteudo)
    if evento is None:
        return None
    raiz, chave, tipo = topico.split("/")
    if (raiz == "sistema" and tipo not in ("status", "rejeitado")) or (raiz == "fila" and tipo not in TOPICOS):
        return None
    payload = evento["payload"]
    if tipo == "leitura":
        # A tentativa aparece ao vivo, mas sem a chave da foto no bucket.
        payload = {c: v for c, v in payload.items() if c != "fotoRef"}
    origem = datetime.fromtimestamp(evento["timestamp"] / 1000).astimezone()
    # O Last Will sai com o horário da conexão que o registrou: latência sem sentido.
    latencia_ms = None if tipo == "status" else (recebido_em - origem).total_seconds() * 1000

    with _trava:
        if tipo == "status":
            componentes[chave] = {"online": payload.get("online") is True, "atualizadoEm": recebido_em}
        elif tipo == "rejeitado":
            rejeitadas[str(payload.get("motivo"))[:40]] += 1
        else:
            situacao = filas_ao_vivo.setdefault(chave, situacao_vazia())
            if tipo == "heartbeat":
                situacao["ultimo_heartbeat"] = recebido_em
                return evento
            if tipo in ("estado", "recomendacao"):
                situacao[tipo] = payload
            elif tipo == "leitura":
                situacao["ultima_leitura"] = {**payload, "recebidoEm": recebido_em}
            elif tipo == "resultado":
                situacao["ultimo_resultado"] = {**payload, "recebidoEm": recebido_em}
            elif tipo == "reacao":
                situacao["ultima_reacao"] = {**payload, "recebidoEm": recebido_em}
        mensagens_recentes.appendleft({
            "recebidoEm": recebido_em, "origem": origem, "latenciaMs": latencia_ms,
            "filaId": chave if raiz == "fila" else None, "tipo": tipo,
            "eventId": evento["event_id"], "correlationId": evento["correlation_id"],
            "source": evento["source"], "payload": payload})
    return evento


def situacao_atual(broker_conectado, agora=None):
    agora = agora or agora_local()
    with _trava:
        filas = []
        for fila, situacao in sorted(filas_ao_vivo.items()):
            ultimo = situacao["ultimo_heartbeat"]
            sem_heartbeat = None if ultimo is None else (agora - ultimo).total_seconds()
            filas.append({
                "filaId": fila, "estado": situacao["estado"],
                "recomendacao": situacao["recomendacao"],
                "ultimaLeitura": situacao["ultima_leitura"],
                "ultimoResultado": situacao["ultimo_resultado"],
                "ultimaReacao": situacao["ultima_reacao"],
                "segundosSemHeartbeat": sem_heartbeat,
                "enlaceAtivo": sem_heartbeat is not None and sem_heartbeat <= LIMITE_SEM_HEARTBEAT_SEGUNDOS,
            })
        return {"brokerConectado": broker_conectado, "filas": filas,
                "componentes": [{"source": nome, **c} for nome, c in sorted(componentes.items())],
                "rejeitadas": dict(rejeitadas),
                "mensagens": list(mensagens_recentes)}
