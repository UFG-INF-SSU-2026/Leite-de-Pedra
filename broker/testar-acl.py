"""Teste de entrega MQTT: leitor autorizado recebe, leitor proibido não recebe.

Execute com o broker do projeto em funcionamento.

O broker usa o usuário como client id, então cada usuário só tem uma conexão.
Por isso o produtor assina e publica pelo mesmo cliente: um segundo cliente
derrubaria o primeiro, e "não recebeu" passaria mesmo com a ACL errada. Pelo
mesmo motivo, o teste derruba os ESP32 produtor e a observabilidade, que
reconectam sozinhos. O leitor permitido é o observador: entrar como processador
apagaria a sessão persistente, com as mensagens guardadas para ele.
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
    caiu = threading.Event()
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

    def on_disconnect(cliente, userdata, flags, reason_code, properties):
        caiu.set()

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_subscribe = on_subscribe
    client.on_message = on_message
    conectar(client, papel)
    client.loop_start()
    if not conectado.wait(3) or (assinar and not inscrito.wait(3)):
        raise RuntimeError(f"Cliente {papel} não ficou pronto")
    return client, recebido, caiu


def main():
    clientes = []
    try:
        observador, recebido_observador, observador_caiu = iniciar("observador", assinar=True)
        clientes.append(observador)
        produtor, recebido_produtor, produtor_caiu = iniciar("produtor", assinar=True)
        clientes.append(produtor)

        envio = produtor.publish(TOPICO, "teste-acl", qos=1)
        envio.wait_for_publish(timeout=3)
        if not envio.is_published():
            raise RuntimeError("Publicação de teste não foi confirmada")
        if not recebido_observador.wait(3):
            raise RuntimeError("Observador não recebeu a telemetria permitida")
        time.sleep(0.5)
        if recebido_produtor.is_set():
            raise RuntimeError("Produtor recebeu telemetria sem permissão de leitura")
        if observador_caiu.is_set() or produtor_caiu.is_set():
            raise RuntimeError("Um cliente caiu durante o teste: resultado inconclusivo")
        print("ACL de leitura: observador recebeu; produtor não recebeu. OK")
    finally:
        for client in clientes:
            client.disconnect()
            client.loop_stop()


if __name__ == "__main__":
    main()
