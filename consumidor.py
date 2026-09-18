import paho.mqtt.client as mqtt
import json
import time
from collections import deque
from datetime import datetime, timedelta
import threading

TOPICO_CONTAGEM = "fila/+/contagem"
TOPICO_VALIDACAO = "fila/+/validacao"
TOPICO_RECOMENDACAO = "fila/{}/recomendacao"

filas = ["fila-a", "fila-b"]

LIMITE_ATENCAO = 5
LIMITE_BLOQUEIO = 10
MARGEM_HISTERESE = 3
VALIDADE_DADOS = timedelta(seconds=6)

NIVEL = {"livre": 0, "atencao": 1, "bloqueada": 2}
ROTULOS = {"livre": "VERDE", "atencao": "AMARELO", "bloqueada": "VERMELHO"}
CORES_SEM_DADOS = "\033[90m● ------\033[0m"

CORES = {
    "livre": "\033[92m● VERDE\033[0m",
    "atencao": "\033[93m● AMARELO\033[0m",
    "bloqueada": "\033[91m● VERMELHO\033[0m",
}

INTERVALO_PAINEL = 2

entradas = {fila: 0 for fila in filas}
saidas = {fila: 0 for fila in filas}
fila_saidas = {fila: deque(maxlen=20) for fila in filas}
semaforo = {fila: "livre" for fila in filas}
ultima_publicacao = {fila: None for fila in filas}
ultimo_heartbeat = {fila: None for fila in filas}

def on_message(client, userdata, msg):
    payload = json.loads(msg.payload.decode())
    fila = payload["filaId"]

    if msg.topic.endswith("/contagem"):
        entradas[fila] += 1
        atualizar_heartbeat(fila)

    elif msg.topic.endswith("/validacao"):
        if payload["resultado"] == "aprovado":
            saidas[fila] += 1
            fila_saidas[fila].append(payload)
        atualizar_heartbeat(fila)

    recomendar_fila(client)

def atualizar_heartbeat(fila):
    ultimo_heartbeat[fila] = datetime.now()

def ocupacao_de(fila):
    return max(0, entradas[fila] - saidas[fila])

def vazao_de(fila, agora):
    if len(fila_saidas[fila]) < 2:
        return 0
    inicio = datetime.fromtimestamp(fila_saidas[fila][0]["eventTimeMs"] / 1000)
    janela = (agora - inicio).total_seconds()
    if janela <= 0:
        return 0
    return len(fila_saidas[fila]) / janela

def classificar(fila, ocupacao):
    atual = semaforo[fila]
    desce_para_livre = LIMITE_ATENCAO - MARGEM_HISTERESE
    desce_para_atencao = LIMITE_BLOQUEIO - MARGEM_HISTERESE

    if atual == "bloqueada":
        if ocupacao <= desce_para_livre:
            return "livre"
        if ocupacao <= desce_para_atencao:
            return "atencao"
        return "bloqueada"

    if atual == "atencao":
        if ocupacao > LIMITE_BLOQUEIO:
            return "bloqueada"
        if ocupacao <= desce_para_livre:
            return "livre"
        return "atencao"

    if ocupacao > LIMITE_BLOQUEIO:
        return "bloqueada"
    if ocupacao > LIMITE_ATENCAO:
        return "atencao"
    return "livre"

def melhor_fila(fila, candidatas, ocupacao):
    # Só vale desviar para uma fila que esteja num estado melhor que esta. Como
    # o estado já tem histerese, a decisão não fica alternando quando as duas
    # filas estão parecidas - e mandar gente para uma fila igualmente cheia não
    # resolveria nada.
    melhores = [c for c in candidatas if NIVEL[semaforo[c]] < NIVEL[semaforo[fila]]]
    if not melhores:
        return fila
    return min(melhores, key=lambda c: ocupacao[c])

def recomendar_fila(client):
    agora = datetime.now()

    atualizadas = [
        fila for fila in filas
        if ultimo_heartbeat[fila] is not None and agora - ultimo_heartbeat[fila] <= VALIDADE_DADOS
    ]

    ocupacao = {}
    tempo_espera = {}
    for fila in atualizadas:
        ocupacao[fila] = ocupacao_de(fila)
        vazao = vazao_de(fila, agora)
        tempo_espera[fila] = ocupacao[fila] / vazao if vazao > 0 else None

    for fila in atualizadas:
        semaforo[fila] = classificar(fila, ocupacao[fila])

    for fila in filas:
        if fila not in atualizadas:
            print(f"Fila {fila} sem dados atualizados - mantendo recomendação anterior")
            continue

        if semaforo[fila] == "livre":
            destino = fila
        else:
            destino = melhor_fila(fila, atualizadas, ocupacao)

        publicar(client, fila, ocupacao[fila], destino, tempo_espera[fila])

def publicar(client, fila, ocupacao, destino, espera):
    estado = (semaforo[fila], destino)
    if ultima_publicacao[fila] == estado:
        return

    anterior = ultima_publicacao[fila]
    payload = {
        "filaId": fila,
        "semaforo": semaforo[fila],
        "ocupacao": ocupacao,
        "sentidoRecomendado": destino,
        "tempoEsperaEstimado": int(espera) if espera is not None else None,
    }
    client.publish(TOPICO_RECOMENDACAO.format(fila), json.dumps(payload))
    ultima_publicacao[fila] = estado

    if anterior is not None and anterior[0] != semaforo[fila]:
        print(f"\n>>> {fila}: {ROTULOS[anterior[0]]} -> {ROTULOS[semaforo[fila]]}"
              f"  ({ocupacao} na fila)\n")

    if anterior is None:
        print(f"{CORES[semaforo[fila]]}  {fila} entrou em operação")

def painel():
    while True:
        time.sleep(INTERVALO_PAINEL)
        agora = datetime.now()
        linhas = []
        for fila in filas:
            if ultimo_heartbeat[fila] is None or agora - ultimo_heartbeat[fila] > VALIDADE_DADOS:
                linhas.append(f"  {fila}  {CORES_SEM_DADOS}  sem dados")
                continue
            ocupacao = ocupacao_de(fila)
            vazao = vazao_de(fila, agora)
            espera = f"~{int(ocupacao / vazao)}s" if vazao > 0 else "  -"
            estado = ultima_publicacao[fila]
            destino = estado[1] if estado else fila
            seta = "permanecer" if destino == fila else f"--> {destino}"
            linhas.append(
                f"  {fila}  {CORES[semaforo[fila]]}  {ocupacao:>2} na fila"
                f"   {vazao:.1f}/s   espera {espera:>4}   {seta}"
            )
        print("\n".join(linhas))

def on_connect(client, userdata, flags, rc):
    client.subscribe(TOPICO_CONTAGEM)
    client.subscribe(TOPICO_VALIDACAO)
    print("Conectado ao broker - assinaturas restabelecidas")

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message
client.connect("localhost", 1883, 60)
threading.Thread(target=painel, daemon=True).start()
client.loop_forever()
