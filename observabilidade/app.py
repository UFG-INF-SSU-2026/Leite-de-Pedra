"""API interna da observabilidade: o ao vivo (broker) e o histórico operacional (banco).

Só monitora: não grava nada e não decide quem pode ver. Sem autenticação: quem
a expõe ao painel é o backend, que confere o admin. Por isso ela escuta só em
127.0.0.1 por padrão e, no Docker, só na rede interna do compose, sem porta
publicada.
"""

import sys
from pathlib import Path

import paho.mqtt.client as mqtt
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from . import ao_vivo, historico  # noqa: E402

TOPICOS = [(f"fila/+/{tipo}", 1) for tipo in ao_vivo.TOPICOS] + [
    ("sistema/+/status", 1), ("sistema/+/rejeitado", 1)]

cliente_mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)


def ao_conectar(client, userdata, flags, reason_code, properties):
    if reason_code != 0:
        print(f"Falha ao autenticar/conectar ao broker MQTT ({reason_code})")
        return
    client.subscribe(TOPICOS)
    print("Observabilidade conectada ao broker")


def ao_receber(client, userdata, mensagem):
    ao_vivo.registrar_mensagem(mensagem.topic, mensagem.payload)


cliente_mqtt.on_connect = ao_conectar
cliente_mqtt.on_message = ao_receber

app = FastAPI(title="Observabilidade", docs_url=None, redoc_url=None)
app.include_router(historico.rotas)


@app.get("/ao-vivo")
def agora():
    return ao_vivo.situacao_atual(cliente_mqtt.is_connected())
