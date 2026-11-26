"""Conexões do backend: AWS (Rekognition e S3), banco por papel e MQTT."""

import os
import sys
import threading
from pathlib import Path

import boto3
import paho.mqtt.client as mqtt
from botocore.config import Config

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from modelos import criar_motor, fabrica_de_sessoes  # noqa: E402
from mqtt_config import ler_evento  # noqa: E402

PASTA_SEGREDOS = RAIZ / ".local" / "backend"
# Situação ao vivo (observabilidade/), repassada ao painel pelas rotas /admin.
URL_OBSERVABILIDADE = os.getenv("OBSERVABILIDADE_URL", "http://127.0.0.1:8090")

COLECAO_ROSTOS = os.getenv("REKOGNITION_COLECAO")
BUCKET_FOTOS = os.getenv("FOTOS_BUCKET")
if not COLECAO_ROSTOS or not BUCKET_FOTOS:
    sys.exit("Defina REKOGNITION_COLECAO e FOTOS_BUCKET.")
_config_aws = Config(connect_timeout=3, read_timeout=5, retries={"max_attempts": 2})
rekognition = boto3.client("rekognition", config=_config_aws)
s3 = boto3.client("s3", config=_config_aws)
rekognition.describe_collection(CollectionId=COLECAO_ROSTOS)

# Rotas do app usam o papel backend; as do dashboard, o papel painel. Cada um
# só tem no banco as permissões das próprias rotas.
sessao_backend = fabrica_de_sessoes(criar_motor("backend"))
sessao_painel = fabrica_de_sessoes(criar_motor("painel"))

cliente_mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
respostas = {}  # correlation_id -> [Event, payload do resultado ou None], leituras esperando o processador
trava_respostas = threading.Lock()


def ao_conectar(client, userdata, flags, reason_code, properties):
    if reason_code != 0:
        print(f"Falha ao autenticar/conectar ao broker MQTT ({reason_code})")
        return
    # Só o que a catraca espera; acompanhar o resto é da observabilidade.
    client.subscribe("fila/+/resultado", 1)
    print("Backend conectado ao broker")


def receber_resultado(evento):
    """Entrega o resultado à leitura que o espera, pelo correlation_id."""
    with trava_respostas:
        espera = respostas.get(evento["correlation_id"])
        if espera:
            espera[1] = evento["payload"]
            espera[0].set()


def ao_receber(client, userdata, mensagem):
    evento = ler_evento(mensagem.topic, mensagem.payload)
    if evento and evento["event_type"] == "resultado":
        receber_resultado(evento)


cliente_mqtt.on_connect = ao_conectar
cliente_mqtt.on_message = ao_receber
