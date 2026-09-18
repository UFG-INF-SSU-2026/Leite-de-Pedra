import paho.mqtt.client as mqtt
import json
from datetime import datetime, timedelta

TOPICO_TODAS_FILAS = "fila/#"

ultimo_heartbeat = {}

def on_message(client, userdata, msg):
    payload = json.loads(msg.payload.decode())
    fila = payload["filaId"]

    tipo_evento = payload.get("tipo", msg.topic.rsplit("/", 1)[-1])
    sequence = payload.get("sequence", "-")

    if "eventTimeMs" in payload:
        timestamp = datetime.fromtimestamp(payload["eventTimeMs"] / 1000)
        latencia = (datetime.now() - timestamp).total_seconds() * 1000
        print(f"[{timestamp}] {fila}: {tipo_evento} seq={sequence} (latência {latencia:.0f}ms)")
    else:
        print(f"[{datetime.now()}] {fila}: {tipo_evento} seq={sequence} (sem carimbo de origem)")

    if tipo_evento == "heartbeat":
        ultimo_heartbeat[fila] = datetime.now()
    else:  
        if fila not in ultimo_heartbeat or datetime.now() - ultimo_heartbeat[fila] > timedelta(seconds=8):
            print(f"ALERTA: fila {fila} sem heartbeat há mais de 8s - enlace pode estar caído")

def on_connect(client, userdata, flags, rc):
    client.subscribe(TOPICO_TODAS_FILAS)
    print("Conectado ao broker - assinatura restabelecida")

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message
client.connect("localhost", 1883, 60)
client.loop_forever()
