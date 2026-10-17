import paho.mqtt.client as mqtt
import json
from datetime import datetime, timedelta
import sys
from pathlib import Path

# Os módulos compartilhados ficam na raiz.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mqtt_config import conectar

# Tudo menos fila/+/leitura: a leitura facial interessa só ao processador.
TOPICOS = ["contagem", "saida", "heartbeat", "resultado", "estado", "recomendacao"]

ultimo_heartbeat = {}

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        fila = payload["filaId"]
    except (ValueError, KeyError, TypeError):
        print(f"Mensagem inválida em {msg.topic}: descartada")
        return

    tipo_evento = payload.get("tipo", msg.topic.rsplit("/", 1)[-1])
    sequence = payload.get("sequence", "-")

    if "eventTimeMs" in payload:
        timestamp = datetime.fromtimestamp(payload["eventTimeMs"] / 1000)
        latencia = (datetime.now() - timestamp).total_seconds() * 1000
        print(f"[{timestamp}] {fila}: {tipo_evento} seq={sequence} (latência {latencia:.0f}ms)")
    else:
        print(f"[{datetime.now()}] {fila}: {tipo_evento} seq={sequence} (sem carimbo de origem)")

    if tipo_evento == "resultado":
        print(f"    leitura {payload.get('eventId')}: {payload.get('resultado')}")

    if "motivo" in payload:
        print(f"    {payload['semaforo']} -> {payload['sentidoRecomendado']}: {payload['motivo']}")

    if tipo_evento == "heartbeat":
        ultimo_heartbeat[fila] = datetime.now()
    else:  
        if fila not in ultimo_heartbeat or datetime.now() - ultimo_heartbeat[fila] > timedelta(seconds=8):
            print(f"ALERTA: fila {fila} sem heartbeat há mais de 8s - enlace pode estar caído")

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code != 0:
        print(f"Falha ao autenticar/conectar ao broker MQTT ({reason_code})")
        return
    client.subscribe([(f"fila/+/{topico}", 0) for topico in TOPICOS])
    print("Conectado ao broker - assinaturas restabelecidas")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
conectar(client, "observador")
client.loop_forever()
