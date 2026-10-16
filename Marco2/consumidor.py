import paho.mqtt.client as mqtt
import json
import time
from collections import deque
from datetime import datetime, timedelta
import threading
import statistics

TOPICO_CONTAGEM = "fila/+/contagem"
TOPICO_VALIDACAO = "fila/+/validacao"
TOPICO_HEARTBEAT = "fila/+/heartbeat"
TOPICO_RECOMENDACAO = "fila/{}/recomendacao"

# As filas não são declaradas: o consumidor as descobre pelos tópicos que
# chegam. Assim ele não precisa ser reiniciado nem reconfigurado quando o
# produtor sobe com outra quantidade de filas.
filas = []

# Os limiares são de TEMPO DE ESPERA ESTIMADO, não de quantidade de pessoas.
# Dez pessoas numa fila não significam nada sozinhas: dependem de quanto tempo
# o validador leva por pessoa. Em tempo de espera o semáforo significa algo que
# quem está chegando entende, e se um validador ficar lento a fila fecha com
# menos gente, automaticamente.
LIMITE_ATENCAO = 15        # segundos de espera estimada
LIMITE_BLOQUEIO = 30
MARGEM_HISTERESE = 7

# Este aqui é de rede, não de fila: quanto tempo sem evento novo até o
# consumidor parar de sinalizar. Não tem relação com os limiares acima.
VALIDADE_DADOS = timedelta(seconds=6)

# A vazão é medida só sobre as passagens recentes. Sem esse corte, uma fila que
# ficou vazia por um tempo arrasta na janela validações antigas e a taxa sai
# diluída por um período em que não havia ninguém para atender - o que faria a
# espera parecer maior do que é.
JANELA_VAZAO = timedelta(seconds=90)

NIVEL = {"livre": 0, "atencao": 1, "bloqueada": 2}
ROTULOS = {"livre": "VERDE", "atencao": "AMARELO", "bloqueada": "VERMELHO"}
CORES_SEM_DADOS = "\033[90m● ------\033[0m"

CORES = {
    "livre": "\033[92m● VERDE\033[0m",
    "atencao": "\033[93m● AMARELO\033[0m",
    "bloqueada": "\033[91m● VERMELHO\033[0m",
}

INTERVALO_PAINEL = 2

entradas = {}
saidas = {}
fila_saidas = {}
semaforo = {}
ultima_publicacao = {}
ultimo_heartbeat = {}

def registrar(fila):
    if fila in entradas:
        return
    entradas[fila] = 0
    saidas[fila] = 0
    fila_saidas[fila] = deque(maxlen=20)
    semaforo[fila] = "livre"
    ultima_publicacao[fila] = None
    ultimo_heartbeat[fila] = None
    filas.append(fila)
    filas.sort()
    print(f"Fila descoberta: {fila} ({len(filas)} no total)")

def on_message(client, userdata, msg):
    payload = json.loads(msg.payload.decode())
    fila = payload["filaId"]
    registrar(fila)

    if msg.topic.endswith("/contagem"):
        entradas[fila] += 1
        atualizar_heartbeat(fila, payload)

    elif msg.topic.endswith("/validacao"):
        if payload["resultado"] == "aprovado":
            saidas[fila] += 1
            instante = datetime.fromtimestamp(payload["eventTimeMs"] / 1000)
            fila_saidas[fila].append((instante, ocupacao_de(fila)))
        atualizar_heartbeat(fila, payload)

    elif msg.topic.endswith("/heartbeat"):
        # Não entra na contabilidade: só prova que o enlace está vivo quando
        # não há movimento na fila. Sem ele o consumidor se declararia sem
        # dados em qualquer período calmo, com o enlace perfeito.
        atualizar_heartbeat(fila, payload)

    recomendar_fila(client)

def atualizar_heartbeat(fila, payload):
    # O frescor é medido pelo instante em que o evento ACONTECEU, não pelo
    # instante em que o pacote chegou. Na volta de uma queda o produtor reenvia
    # o que acumulou: esses eventos entram na contabilidade, porque ninguém que
    # passou pela fila pode ser perdido, mas não fazem o consumidor se declarar
    # atualizado. A recomendação só volta quando chegar evento recente de fato.
    origem = datetime.fromtimestamp(payload["eventTimeMs"] / 1000)
    if ultimo_heartbeat[fila] is None or origem > ultimo_heartbeat[fila]:
        ultimo_heartbeat[fila] = origem

def ocupacao_de(fila):
    return max(0, entradas[fila] - saidas[fila])

def passagens_recentes(fila, agora):
    limite = agora - JANELA_VAZAO
    return [p for p in fila_saidas[fila] if p[0] >= limite]

def vazao_de(fila, agora):
    # Só conta como atendimento o intervalo em que sabíamos haver alguém
    # esperando: cada passagem registra quanta gente ficou na fila, e se ficou
    # zero o intervalo seguinte foi de fila vazia, não de validador ocupado.
    # Sem essa separação a ociosidade entra na conta e a espera parece maior do
    # que é - com a fila-b chegando a mostrar 39s para 2 pessoas.
    recentes = passagens_recentes(fila, agora)
    if len(recentes) < 2:
        return 0

    atendimentos = [
        (depois[0] - antes[0]).total_seconds()
        for antes, depois in zip(recentes, recentes[1:])
        if antes[1] > 0 and depois[0] > antes[0]
    ]
    if not atendimentos:
        return 0
    return 1 / statistics.mean(atendimentos)

def espera_de(fila, agora):
    ocupacao = ocupacao_de(fila)
    if ocupacao == 0:
        return 0

    # Fila com gente e nenhuma passagem recente pode ser duas coisas muito
    # diferentes. Se esta fila JÁ atendeu alguém antes e parou, o validador
    # travou: a espera é indeterminada e o seguro é fechar. Se ela nunca
    # atendeu ninguém, é só uma fila recém-aberta - não há o que concluir, e
    # declarar bloqueio aí fecharia a fila na chegada da primeira pessoa.
    if not passagens_recentes(fila, agora):
        return float("inf") if fila_saidas[fila] else None

    vazao = vazao_de(fila, agora)
    if vazao == 0:
        return None
    return ocupacao / vazao

def classificar(fila, espera):
    atual = semaforo[fila]

    # Sem vazão medida ainda não há como estimar espera; mantém o estado atual
    # em vez de inventar um. Se o validador parar, a janela de medição se
    # alarga sozinha, a vazão cai e a espera sobe - a fila fecha sem caso especial.
    if espera is None:
        return atual

    desce_para_livre = LIMITE_ATENCAO - MARGEM_HISTERESE
    desce_para_atencao = LIMITE_BLOQUEIO - MARGEM_HISTERESE

    if atual == "bloqueada":
        if espera <= desce_para_livre:
            return "livre"
        if espera <= desce_para_atencao:
            return "atencao"
        return "bloqueada"

    if atual == "atencao":
        if espera > LIMITE_BLOQUEIO:
            return "bloqueada"
        if espera <= desce_para_livre:
            return "livre"
        return "atencao"

    if espera > LIMITE_BLOQUEIO:
        return "bloqueada"
    if espera > LIMITE_ATENCAO:
        return "atencao"
    return "livre"

def melhor_fila(fila, candidatas, tempo_espera):
    # Só vale desviar para uma fila que esteja num estado melhor que esta. Como
    # o estado já tem histerese, a decisão não fica alternando quando as duas
    # filas estão parecidas - e mandar gente para uma fila igualmente cheia não
    # resolveria nada.
    melhores = [c for c in candidatas if NIVEL[semaforo[c]] < NIVEL[semaforo[fila]]]
    if not melhores:
        return fila
    return min(melhores, key=lambda c: tempo_espera[c] if tempo_espera[c] is not None else float("inf"))

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
        tempo_espera[fila] = espera_de(fila, agora)

    for fila in atualizadas:
        semaforo[fila] = classificar(fila, tempo_espera[fila])

    for fila in filas:
        if fila not in atualizadas:
            print(f"Fila {fila} sem dados atualizados - mantendo recomendação anterior")
            continue

        if semaforo[fila] == "livre":
            destino = fila
        else:
            destino = melhor_fila(fila, atualizadas, tempo_espera)

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
        "tempoEsperaEstimado": (
            int(espera) if espera is not None and espera != float("inf") else None
        ),
    }
    client.publish(TOPICO_RECOMENDACAO.format(fila), json.dumps(payload))
    ultima_publicacao[fila] = estado

    if anterior is not None and anterior[0] != semaforo[fila]:
        if espera is None or espera == float("inf"):
            estimada = "espera indeterminada"
        else:
            estimada = f"{int(espera)}s de espera"
        print(f"\n>>> {fila}: {ROTULOS[anterior[0]]} -> {ROTULOS[semaforo[fila]]}"
              f"  ({estimada}, {ocupacao} na fila)\n")

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
            estimada = espera_de(fila, agora)
            if estimada is None:
                espera = "    -"
            elif estimada == float("inf"):
                espera = "parada"
            else:
                espera = f"~{int(estimada)}s"
            estado = ultima_publicacao[fila]
            destino = estado[1] if estado else fila
            seta = "permanecer" if destino == fila else f"--> {destino}"
            linhas.append(
                f"  {fila}  {CORES[semaforo[fila]]}  espera {espera:>5}"
                f"   {ocupacao:>2} na fila   {vazao:.2f}/s   {seta}"
            )
        print("\n".join(linhas))

def on_connect(client, userdata, flags, rc):
    client.subscribe(TOPICO_CONTAGEM)
    client.subscribe(TOPICO_VALIDACAO)
    client.subscribe(TOPICO_HEARTBEAT)
    print("Conectado ao broker - assinaturas restabelecidas")

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message
client.connect("localhost", 1883, 60)
threading.Thread(target=painel, daemon=True).start()
client.loop_forever()
