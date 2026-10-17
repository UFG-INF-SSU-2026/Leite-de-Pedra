import json
import threading
from collections import deque
from datetime import datetime

import paho.mqtt.client as mqtt

from mqtt_config import conectar

from .configuracao import (LIMITE_SEM_HEARTBEAT_SEGUNDOS, QUANTIDADE_MENSAGENS_RECENTES,
                           TOPICOS_ASSINADOS)

mudancas = threading.Condition()
filas_ao_vivo = {}
mensagens_recentes = deque(maxlen=QUANTIDADE_MENSAGENS_RECENTES)
cliente_mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)


def agora_local():
    return datetime.now().astimezone()


def momento_de_origem(payload):
    momento = payload.get("eventTimeMs")
    if isinstance(momento, int) and not isinstance(momento, bool) and 0 < momento < 10**14:
        return datetime.fromtimestamp(momento / 1000).astimezone()
    return None


def situacao_vazia():
    return {"estado": None, "recomendacao": None, "ultimo_heartbeat": None,
            "ultimo_resultado": None, "entradas": 0, "saidas": 0}


def registrar_mensagem(topico, conteudo, recebido_em=None):
    recebido_em = recebido_em or agora_local()
    try:
        payload = json.loads(conteudo)
    except ValueError:
        print(f"Payload que não é JSON em {topico}: descartado")
        return False
    partes = topico.split("/")
    if (len(partes) != 3 or partes[2] not in TOPICOS_ASSINADOS or not isinstance(payload, dict)
            or payload.get("filaId") != partes[1]):
        print(f"Mensagem inválida em {topico}: descartada")
        return False
    fila, tipo = partes[1], partes[2]
    origem = momento_de_origem(payload)
    latencia_ms = None if origem is None else (recebido_em - origem).total_seconds() * 1000

    with mudancas:
        situacao = filas_ao_vivo.setdefault(fila, situacao_vazia())
        if tipo == "heartbeat":
            situacao["ultimo_heartbeat"] = recebido_em
        else:
            if tipo == "estado":
                situacao["estado"] = payload
            elif tipo == "recomendacao":
                situacao["recomendacao"] = payload
            elif tipo == "resultado":
                situacao["ultimo_resultado"] = {**payload, "recebido_em": recebido_em}
            elif tipo == "contagem":
                situacao["entradas"] += 1
            elif tipo == "saida":
                situacao["saidas"] += 1
            mensagens_recentes.appendleft({
                "recebido_em": recebido_em, "origem": origem, "latencia_ms": latencia_ms,
                "fila_id": fila, "tipo": tipo, "payload": payload})
            texto_latencia = "" if latencia_ms is None else f" (latência {latencia_ms:.0f} ms)"
            print(f"{fila}: {tipo}{texto_latencia}")
        mudancas.notify_all()
    return True


def situacao_atual(agora=None):
    agora = agora or agora_local()
    with mudancas:
        filas = []
        for fila, situacao in sorted(filas_ao_vivo.items()):
            ultimo = situacao["ultimo_heartbeat"]
            segundos_sem_heartbeat = None if ultimo is None else (agora - ultimo).total_seconds()
            filas.append({
                **situacao, "fila_id": fila,
                "segundos_sem_heartbeat": segundos_sem_heartbeat,
                "enlace_ativo": segundos_sem_heartbeat is not None
                and segundos_sem_heartbeat <= LIMITE_SEM_HEARTBEAT_SEGUNDOS})
        return {"filas": filas, "mensagens": list(mensagens_recentes),
                "broker_conectado": cliente_mqtt.is_connected()}


def esperar_mudanca(segundos):
    with mudancas:
        mudancas.wait(segundos)


def ao_conectar(client, userdata, flags, reason_code, properties):
    if reason_code != 0:
        print(f"Falha ao autenticar/conectar ao broker MQTT ({reason_code})")
        return
    client.subscribe([(f"fila/+/{topico}", 1) for topico in TOPICOS_ASSINADOS])
    print("Painel conectado ao broker - assinaturas restabelecidas")


def ao_receber(client, userdata, mensagem):
    registrar_mensagem(mensagem.topic, mensagem.payload)


def iniciar_assinatura():
    cliente_mqtt.on_connect = ao_conectar
    cliente_mqtt.on_message = ao_receber
    conectar(cliente_mqtt, "observador", assincrono=True)
    cliente_mqtt.loop_start()


def encerrar_assinatura():
    cliente_mqtt.disconnect()
    cliente_mqtt.loop_stop()
