"""Teste de entrega MQTT: leitor autorizado recebe, leitor proibido não recebe.

Execute com o broker do projeto em funcionamento.
"""

import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mqtt_config import conectar


TOPICO = "fila/teste-marco3/heartbeat"


def iniciar(papel, assinar=False):
    conectado = threading.Event()
    inscrito = threading.Event()
    recebido = threading.Event()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def on_connect(cliente, userdata, flags, reason_code, properties):
        if reason_code != 0:
            print(f"Falha ao conectar {papel}: {reason_code}", file=sys.stderr)
            return
        if assinar:
            cliente.subscribe(TOPICO)
        conectado.set()

    def on_subscribe(cliente, userdata, mid, reason_codes, properties):
        inscrito.set()

    def on_message(cliente, userdata, mensagem):
        recebido.set()

    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    conectar(client, papel)
    client.loop_start()
    if not conectado.wait(3) or (assinar and not inscrito.wait(3)):
        raise RuntimeError(f"Cliente {papel} não ficou pronto")
    return client, recebido


def main():
    clientes = []
    try:
        processador, recebido_processador = iniciar("processador", assinar=True)
        clientes.append(processador)
        leitor_proibido, recebido_produtor = iniciar("produtor", assinar=True)
        clientes.append(leitor_proibido)
        produtor, _ = iniciar("produtor")
        clientes.append(produtor)

        envio = produtor.publish(TOPICO, "teste-acl", qos=1)
        envio.wait_for_publish(timeout=3)
        if not envio.is_published():
            raise RuntimeError("Publicação de teste não foi confirmada")
        if not recebido_processador.wait(3):
            raise RuntimeError("Processador não recebeu a telemetria permitida")
        time.sleep(0.5)
        if recebido_produtor.is_set():
            raise RuntimeError("Produtor recebeu telemetria sem permissão de leitura")
        print("ACL de leitura: processador recebeu; produtor não recebeu. OK")
    finally:
        for client in clientes:
            client.disconnect()
            client.loop_stop()


if __name__ == "__main__":
    main()
