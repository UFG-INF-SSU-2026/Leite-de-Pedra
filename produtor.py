import paho.mqtt.client as mqtt
import json
from collections import deque
from datetime import datetime
import itertools
import time
import random
import threading

TOPICO_CONTAGEM = "fila/{}/contagem"
TOPICO_VALIDACAO = "fila/{}/validacao"
TOPICO_HEARTBEAT = "fila/{}/heartbeat"
TOPICO_RECOMENDACAO = "fila/+/recomendacao"

filas = ["fila-a", "fila-b"]

# Regime normal: as duas filas recebem menos gente do que os validadores
# conseguem atender, então ambas ficam verdes e ninguém é desviado.
INTERVALO_CHEGADA = {"fila-a": 1.5, "fila-b": 2.0}
INTERVALO_ATENDIMENTO = {"fila-a": 0.8, "fila-b": 0.8}
TAXA_REPROVACAO = 0.15

# Picos de entrada periódicos, alternando de fila. Num evento real os picos se
# repetem e não se concentram sempre na mesma entrada; repetir também garante
# que a demonstração sempre tenha um ciclo à vista.
PICO_ATRASO = 12      # primeiro pico, em segundos após a partida
PICO_DURACAO = 10     # quanto tempo o pico dura
CICLO_PICO = 40       # de quanto em quanto tempo ele volta
INTERVALO_PICO = 0.25

partida = time.monotonic()
pico_anterior = {"fila": None}

def fila_em_pico():
    decorrido = time.monotonic() - partida
    if decorrido < PICO_ATRASO:
        return None
    desde_o_primeiro = decorrido - PICO_ATRASO
    if desde_o_primeiro % CICLO_PICO >= PICO_DURACAO:
        return None
    return filas[int(desde_o_primeiro // CICLO_PICO) % len(filas)]

def intervalo_de_chegada(fila):
    return INTERVALO_PICO if fila_em_pico() == fila else INTERVALO_CHEGADA[fila]

def anunciar_pico():
    atual = fila_em_pico()
    if atual != pico_anterior["fila"]:
        anterior = pico_anterior["fila"]
        pico_anterior["fila"] = atual
        if atual:
            print(f"\n>>> PICO DE ENTRADA na {atual} <<<\n")
        else:
            print(f"\n>>> fim do pico na {anterior} - chegadas voltam ao normal <<<\n")

na_fila = {fila: 0 for fila in filas}
destino_atual = {fila: fila for fila in filas}
contador = {
    "contagem": itertools.count(1),
    "validacao": itertools.count(1),
    "heartbeat": itertools.count(1),
}

fila_local = deque(maxlen=200)
trava_envio = threading.Lock()
trava_fila = threading.Lock()

def topico_de(fila, tipo):
    if tipo == "contagem":
        return TOPICO_CONTAGEM.format(fila)
    if tipo == "validacao":
        return TOPICO_VALIDACAO.format(fila)
    return TOPICO_HEARTBEAT.format(fila)

def publicar_evento(client, fila, tipo, extra=None):
    payload = {
        "filaId": fila,
        "tipo": tipo,
        "sequence": next(contador[tipo]),
        "eventTimeMs": int(datetime.now().timestamp() * 1000),
    }
    if extra:
        payload.update(extra)

    with trava_envio:
        esvaziar_fila_local(client)
        entregar(client, topico_de(fila, tipo), payload)

def entregar(client, topico, payload):
    if client.publish(topico, json.dumps(payload)).rc != mqtt.MQTT_ERR_SUCCESS:
        fila_local.append((topico, payload))
        print(f"Sem enlace: evento acumulado na fila local ({len(fila_local)} pendentes) = {payload}")
        return
    print(f"Publicado: {topico} = {payload}")

def esvaziar_fila_local(client):
    while fila_local:
        topico, payload = fila_local[0]
        if client.publish(topico, json.dumps(payload)).rc != mqtt.MQTT_ERR_SUCCESS:
            return
        fila_local.popleft()
        print(f"Reenviado da fila local: {topico} = {payload}")

def simular_chegadas(client, fila):
    while True:
        time.sleep(intervalo_de_chegada(fila))
        anunciar_pico()

        # A pessoa chega procurando esta fila, mas obedece ao semáforo: se ele
        # não estiver verde, ela entra na fila indicada. Quem a conta é o
        # infravermelho da fila em que ela realmente entrou.
        escolhida = destino_atual[fila]

        with trava_fila:
            na_fila[escolhida] += 1
            presentes = na_fila[escolhida]

        publicar_evento(client, escolhida, "contagem")
        if escolhida != fila:
            print(f"   (desvio: chegou em {fila}, entrou em {escolhida} - {presentes} na fila)")
        else:
            print(f"   (infravermelho {fila}: {presentes} pessoas na fila)")

def simular_atendimentos(client, fila):
    while True:
        time.sleep(INTERVALO_ATENDIMENTO[fila])
        with trava_fila:
            if na_fila[fila] == 0:
                continue
            aprovado = random.random() > TAXA_REPROVACAO
            if aprovado:
                na_fila[fila] -= 1
        publicar_evento(client, fila, "validacao",
                        {"resultado": "aprovado" if aprovado else "reprovado"})

def simular_heartbeats(client):
    while True:
        for fila in filas:
            publicar_evento(client, fila, "heartbeat")
        time.sleep(2)

def on_recomendacao(client, userdata, msg):
    payload = json.loads(msg.payload.decode())
    destino_atual[payload["filaId"]] = payload["sentidoRecomendado"]

def on_connect(client, userdata, flags, rc):
    client.subscribe(TOPICO_RECOMENDACAO)

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_recomendacao
client.connect("localhost", 1883, 60)
client.loop_start()

for fila in filas:
    threading.Thread(target=simular_chegadas, args=(client, fila), daemon=True).start()
    threading.Thread(target=simular_atendimentos, args=(client, fila), daemon=True).start()

simular_heartbeats(client)
