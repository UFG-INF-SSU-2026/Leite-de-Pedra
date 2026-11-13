import paho.mqtt.client as mqtt
import json
import time
from collections import deque
from datetime import datetime, timedelta
import threading
import statistics
import sys
from pathlib import Path

from sqlalchemy.exc import DBAPIError

# Os módulos compartilhados ficam na raiz.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from estado_filas import EstadoFilas
from mqtt_config import conectar, desconectar, evento, ler_evento

TOPICO_CONTAGEM = "fila/+/contagem"
TOPICO_SAIDA = "fila/+/saida"
TOPICO_HEARTBEAT = "fila/+/heartbeat"
TOPICO_LEITURA = "fila/+/leitura"
TOPICO_RECOMENDACAO = "fila/{}/recomendacao"
TOPICO_ESTADO = "fila/{}/estado"
TOPICO_RESULTADO = "fila/{}/resultado"
# Fila de mensagens com falha: o que o processador descartou, e por quê.
TOPICO_REJEITADO = "sistema/processador/rejeitado"
INTERVALO_SAIDA_SEGUNDOS = 5  # nova tentativa do que o broker não confirmou

# O rosto é reconhecido pelo backend (Rekognition), que publica a leitura com
# o usuário reconhecido; só o backend pode publicar leituras (ACL). Aqui ficam
# as regras do ingresso: quem leu é validador, o ingresso é do dono do rosto,
# não foi usado nem cancelado. Sem AWS no processador.
RECONHECIMENTOS = {"reconhecido", "nao-reconhecido", "falha"}

# As filas não são declaradas: o processador as descobre pelos tópicos que
# chegam. Assim ele não precisa ser reiniciado nem reconfigurado quando o
# produtor sobe com outra quantidade de filas.
filas = []

# Os limiares são de TEMPO DE ESPERA ESTIMADO, não de quantidade de pessoas.
# Dez pessoas numa fila não significam nada sozinhas: dependem de quanto tempo
# a entrada leva por pessoa. Em tempo de espera o semáforo significa algo que
# quem está chegando entende, e se a entrada ficar lenta a fila fecha com
# menos gente, automaticamente.
LIMITE_ATENCAO = 15        # segundos de espera estimada
LIMITE_BLOQUEIO = 30
MARGEM_HISTERESE = 7

# Este aqui é de rede, não de fila: limite sem heartbeat RECEBIDO pelo
# processador. A folga considera o Wokwi rodando abaixo de 100% da velocidade.
VALIDADE_DADOS_SEGUNDOS = 15

# A vazão é medida só sobre as passagens recentes. Sem esse corte, uma fila que
# ficou vazia por um tempo arrasta na janela saídas antigas e a taxa sai
# diluída por um período em que não havia ninguém para atender - o que faria a
# espera parecer maior do que é.
JANELA_VAZAO = timedelta(seconds=90)
TEMPO_PASSAGEM_INICIAL = 7  # estimativa até o sensor de saída registrar duas passagens

NIVEL = {"livre": 0, "atencao": 1, "bloqueada": 2}
ROTULOS = {"livre": "VERDE", "atencao": "AMARELO", "bloqueada": "VERMELHO"}
CORES_SEM_DADOS = "\033[90m● ------\033[0m"

CORES = {
    "livre": "\033[92m● VERDE\033[0m",
    "atencao": "\033[93m● AMARELO\033[0m",
    "bloqueada": "\033[91m● VERMELHO\033[0m",
}

INTERVALO_PAINEL = 2

estado_persistente = EstadoFilas()
entradas = {}
saidas = {}
fila_saidas = {}
semaforo = {}
ultima_publicacao = {}
ultimo_heartbeat_recebido = {}
ultimo_estado_publicado = {}
# mid do Paho -> event_id da saída (outbox) publicada e ainda sem PUBACK.
aguardando_puback = {}
trava_saida = threading.Lock()
falhou = False

def registrar(fila):
    if fila in entradas:
        return
    entradas[fila] = 0
    saidas[fila] = 0
    fila_saidas[fila] = deque(maxlen=20)
    semaforo[fila] = "livre"
    ultima_publicacao[fila] = None
    ultimo_heartbeat_recebido[fila] = None
    ultimo_estado_publicado[fila] = None
    filas.append(fila)
    filas.sort()
    print(f"Fila descoberta: {fila} ({len(filas)} no total)")

def on_message(client, userdata, msg):
    try:
        if processar_mensagem(client, msg):
            client.ack(msg.mid, msg.qos)
    except DBAPIError as erro:
        desconectar_sem_confirmar(client, erro)

def desconectar_sem_confirmar(client, erro):
    global falhou
    falhou = True
    print(f"Falha no banco: {erro}. Desconectando sem confirmar as mensagens pendentes.")
    desconectar(client, "processador")

def rejeitar(client, msg, motivo, recebido=None):
    """Publica o descarte em TOPICO_REJEITADO, para a observabilidade, e confirma a mensagem."""
    print(f"Mensagem rejeitada em {msg.topic}: {motivo}")
    payload = {"topico": msg.topic, "motivo": motivo}
    if recebido:
        payload["eventId"] = recebido["event_id"]
    elif not msg.topic.endswith("/leitura"):  # leitura não vai para fora, nem malformada
        payload["conteudo"] = msg.payload[:300].decode("utf-8", "replace")
    rejeicao = evento("rejeitado", "processador", payload,
                      correlation_id=recebido["correlation_id"] if recebido else None)
    client.publish(TOPICO_REJEITADO, json.dumps(rejeicao), qos=1)
    return True

def processar_mensagem(client, msg):
    recebido = ler_evento(msg.topic, msg.payload)
    if recebido is None:
        return rejeitar(client, msg, "fora-do-contrato")
    _, fila, tipo = msg.topic.split("/")
    if tipo not in {"contagem", "saida", "heartbeat", "leitura"}:
        return rejeitar(client, msg, "tipo-desconhecido", recebido)

    if tipo == "leitura":
        payload = recebido["payload"]
        campos = ("fotoRef", "ingressoId", "validadorId")
        reconhecido = payload.get("reconhecimento") == "reconhecido"
        if (not all(texto_valido(payload.get(c)) for c in campos)
                or payload.get("reconhecimento") not in RECONHECIMENTOS
                or not isinstance(payload.get("validoAte"), int)
                or reconhecido != texto_valido(payload.get("usuarioReconhecido"))):
            return rejeitar(client, msg, "leitura-incompleta", recebido)
        estado_persistente.aplicar(fila, recebido)
        # Passado o prazo, o backend já respondeu 504 e o operador decidiu na mão:
        # decidir agora gastaria o ingresso de quem pode nem ter entrado.
        if payload["validoAte"] < time.time() * 1000:
            return rejeitar(client, msg, "leitura-expirada", recebido)
        if not decidir_leitura(client, recebido):
            rejeitar(client, msg, "duplicado", recebido)  # a resposta já gravada sai de novo
        return True

    registrar(fila)

    if tipo in {"contagem", "saida"}:
        saidas_antes = saidas[fila]
        novo, entradas[fila], saidas[fila] = estado_persistente.aplicar(fila, recebido)
        if not novo:
            return rejeitar(client, msg, "duplicado", recebido)
        if tipo == "saida" and saidas[fila] > saidas_antes:
            instante = datetime.fromtimestamp(recebido["timestamp"] / 1000)
            fila_saidas[fila].append((instante, ocupacao_de(fila)))
    elif tipo == "heartbeat":
        # Não entra na contabilidade: só prova que o enlace está vivo quando
        # não há movimento na fila. Sem ele o processador se declararia sem
        # dados em qualquer período calmo, com o enlace perfeito.
        ultimo_heartbeat_recebido[fila] = time.monotonic()

    recomendar_fila(client, recebido["correlation_id"])
    return True

def texto_valido(valor):
    return isinstance(valor, str) and 0 < len(valor) <= 256

def resultado_de(leitura):
    """A publicação do resultado da leitura, para a saída: (event_id, tópico, conteúdo)."""
    dados = leitura["payload"]

    def montar(resultado, motivo, momento_ms):
        payload = {
            "filaId": dados["filaId"],
            "leituraId": leitura["event_id"],
            "ingressoId": dados["ingressoId"],
            "resultado": resultado,
        }
        if motivo:
            payload["motivo"] = motivo
        # event_id derivado da leitura: a resposta repetida numa reentrega é o mesmo evento.
        mensagem = evento("resultado", "processador", payload, correlation_id=leitura["correlation_id"],
                          event_id=f"{leitura['event_id']}-resultado", timestamp=momento_ms)
        return mensagem["event_id"], TOPICO_RESULTADO.format(dados["filaId"]), json.dumps(mensagem)
    return montar

def publicar_saida(client):
    """Publica o que está na saída (outbox) e o broker ainda não confirmou.

    A confirmação (PUBACK) chega em on_publish, que marca publicado_em. O que
    estava no ar numa queda sai de novo: quem consome deduplica pelo event_id.
    """
    with trava_saida:
        no_ar = set(aguardando_puback.values())
        for evento_id, topico, conteudo in estado_persistente.saida_pendente():
            if evento_id in no_ar:
                continue
            envio = client.publish(topico, conteudo, qos=1)
            if envio.rc == mqtt.MQTT_ERR_SUCCESS:
                aguardando_puback[envio.mid] = evento_id

def on_publish(client, userdata, mid, reason_code, properties):
    with trava_saida:
        evento_id = aguardando_puback.pop(mid, None)
    if evento_id is None:
        return
    try:
        estado_persistente.marcar_publicado(evento_id)
    except DBAPIError as erro:
        # Continua pendente: sai de novo na próxima tentativa, com o mesmo event_id.
        print(f"Falha ao marcar {evento_id} como publicado: {erro}")

def retransmitir(client):
    while True:
        time.sleep(INTERVALO_SAIDA_SEGUNDOS)
        if not client.is_connected():
            continue
        try:
            publicar_saida(client)
        except DBAPIError as erro:
            print(f"Falha ao ler a saída: {erro}")

def decidir_leitura(client, leitura):
    """Decide e grava a leitura com o resultado na saída; False se ela já tinha sido decidida."""
    dados = leitura["payload"]
    usuario = dados.get("usuarioReconhecido")
    # Primeiro quem enviou: só um validador libera entrada.
    if not estado_persistente.e_validador(dados["validadorId"]):
        resultado, motivo = "recusado", "validador-nao-autorizado"
    elif dados["reconhecimento"] == "falha":
        # Sem resposta do reconhecimento o operador decide manualmente.
        resultado, motivo = "indeterminado", "falha-reconhecimento"
    elif dados["reconhecimento"] == "nao-reconhecido":
        resultado, motivo = "recusado", "rosto-nao-confere"
    else:
        resultado, motivo = "aceito", None
    # Depois o ingresso: o banco confirma que é do dono do rosto e que não foi usado.
    # Numa reentrega, devolve a decisão já gravada, sem gastar outro ingresso.
    resultado, motivo, _, nova = estado_persistente.registrar_resultado(
        leitura["event_id"], dados["filaId"], int(time.time() * 1000), dados["ingressoId"],
        resultado, motivo, usuario, dados["validadorId"], leitura["correlation_id"],
        mensagem=resultado_de(leitura))
    publicar_saida(client)
    print(f"Leitura {leitura['event_id']} na {dados['filaId']}, ingresso {dados['ingressoId']}: "
          f"{resultado}" + (f" ({motivo})" if motivo else ""))
    return nova

def heartbeat_recente(fila, agora_monotonico):
    ultimo = ultimo_heartbeat_recebido[fila]
    return ultimo is not None and agora_monotonico - ultimo <= VALIDADE_DADOS_SEGUNDOS

def ocupacao_de(fila):
    return max(0, entradas[fila] - saidas[fila])

def passagens_recentes(fila, agora):
    limite = agora - JANELA_VAZAO
    return [p for p in fila_saidas[fila] if p[0] >= limite]

def vazao_de(fila, agora):
    # Só conta como atendimento o intervalo em que sabíamos haver alguém
    # esperando: cada passagem registra quanta gente ficou na fila, e se ficou
    # zero o intervalo seguinte foi de fila vazia, não de entrada ocupada.
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

    # Antes de medir a vazão, usa uma duração inicial por pessoa. Assim uma
    # fila que cresce já pode ficar amarela ou vermelha. Após atender pessoas,
    # se passar a janela inteira sem saída, considera a entrada parada.
    if not passagens_recentes(fila, agora):
        return float("inf") if fila_saidas[fila] else ocupacao * TEMPO_PASSAGEM_INICIAL

    vazao = vazao_de(fila, agora)
    if vazao == 0:
        return ocupacao * TEMPO_PASSAGEM_INICIAL
    return ocupacao / vazao

def classificar(fila, espera):
    atual = semaforo[fila]

    # Sem vazão medida ainda não há como estimar espera; mantém o estado atual
    # em vez de inventar um. Se a entrada parar, a janela de medição se
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

def espera_texto(espera):
    if espera is None or espera == float("inf"):
        return "espera indeterminada"
    return f"{int(espera)}s de espera"

def situacao_de(fila, ocupacao, tempo_espera):
    return (f"{fila} está {ROTULOS[semaforo[fila]]} "
            f"({espera_texto(tempo_espera[fila])}, {ocupacao[fila]} na fila)")

def motivo_de(fila, destino, ocupacao, tempo_espera):
    # O motivo sai junto com a recomendação para que quem observa - e quem foi
    # desviado - saiba por que a pessoa foi mandada para outra fila, e não só
    # para onde.
    if semaforo[fila] == "livre":
        return f"{situacao_de(fila, ocupacao, tempo_espera)}: sem motivo para desviar"
    if destino == fila:
        return (f"{situacao_de(fila, ocupacao, tempo_espera)}, "
                f"mas nenhuma outra fila está em estado melhor")
    return (f"{situacao_de(fila, ocupacao, tempo_espera)}; "
            f"{situacao_de(destino, ocupacao, tempo_espera)}")

def recomendar_fila(client, correlacao):
    """Publica estado e recomendação; correlacao é a do evento que provocou o recálculo."""
    agora = datetime.now()
    agora_monotonico = time.monotonic()

    atualizadas = [
        fila for fila in filas
        if heartbeat_recente(fila, agora_monotonico)
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

        motivo = motivo_de(fila, destino, ocupacao, tempo_espera)
        publicar(client, fila, ocupacao[fila], destino, tempo_espera[fila], motivo, correlacao)
        publicar_estado(client, fila, ocupacao[fila], destino, tempo_espera[fila], correlacao)

def publicar_estado(client, fila, ocupacao, destino, espera, correlacao):
    estado = (semaforo[fila], ocupacao, destino, int(espera) if espera is not None and espera != float("inf") else None)
    if ultimo_estado_publicado[fila] == estado:
        return
    payload = {
        "filaId": fila,
        "semaforo": estado[0],
        "ocupacao": estado[1],
        "sentidoRecomendado": estado[2],
        "tempoEsperaEstimado": estado[3],
    }
    mensagem = evento("estado", "processador", payload, correlation_id=correlacao)
    resultado = client.publish(TOPICO_ESTADO.format(fila), json.dumps(mensagem), qos=1, retain=True)
    if resultado.rc == mqtt.MQTT_ERR_SUCCESS:
        ultimo_estado_publicado[fila] = estado
        estado_persistente.registrar_estado(fila, *estado[:2], estado[3])

def publicar(client, fila, ocupacao, destino, espera, motivo, correlacao):
    estado = (semaforo[fila], destino)
    if ultima_publicacao[fila] == estado:
        return

    anterior = ultima_publicacao[fila]
    payload = {
        "filaId": fila,
        "semaforo": semaforo[fila],
        "ocupacao": ocupacao,
        "sentidoRecomendado": destino,
        "motivo": motivo,
        "tempoEsperaEstimado": (
            int(espera) if espera is not None and espera != float("inf") else None
        ),
    }
    mensagem = evento("recomendacao", "processador", payload, correlation_id=correlacao)
    client.publish(TOPICO_RECOMENDACAO.format(fila), json.dumps(mensagem), qos=1, retain=True)
    ultima_publicacao[fila] = estado

    if anterior is not None and anterior != estado:
        if anterior[0] != semaforo[fila]:
            cabecalho = f"{fila}: {ROTULOS[anterior[0]]} -> {ROTULOS[semaforo[fila]]}"
        else:
            cabecalho = f"{fila}: {ROTULOS[semaforo[fila]]}, destino {anterior[1]} -> {destino}"
        print(f"\n>>> {cabecalho}\n    motivo: {motivo}\n")

    if anterior is None:
        print(f"{CORES[semaforo[fila]]}  {fila} entrou em operação")

def painel():
    while True:
        time.sleep(INTERVALO_PAINEL)
        agora = datetime.now()
        agora_monotonico = time.monotonic()
        linhas = []
        for fila in filas:
            if not heartbeat_recente(fila, agora_monotonico):
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

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code != 0:
        print(f"Falha ao autenticar/conectar ao broker MQTT ({reason_code})")
        return
    client.subscribe([(TOPICO_CONTAGEM, 1), (TOPICO_SAIDA, 1),
                      (TOPICO_HEARTBEAT, 1), (TOPICO_LEITURA, 1)])
    # Um broker reiniciado perde publicações retidas; republicar após o
    # primeiro heartbeat sem depender de mudança no estado da fila.
    for fila in filas:
        ultima_publicacao[fila] = None
        ultimo_estado_publicado[fila] = None
        ultimo_heartbeat_recebido[fila] = None
    # O que estava sem PUBACK na queda sai de novo, junto com o que ficou na saída.
    with trava_saida:
        aguardando_puback.clear()
    try:
        publicar_saida(client)
    except DBAPIError as erro:
        print(f"Falha ao ler a saída: {erro}")  # retransmitir tenta de novo
    print("Conectado ao broker - assinaturas restabelecidas")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="processador",
                     clean_session=False)
client.manual_ack_set(True)
client.on_connect = on_connect
client.on_message = on_message
client.on_publish = on_publish
for fila_salva, entradas_salvas, saidas_salvas in estado_persistente.listar():
    registrar(fila_salva)
    entradas[fila_salva] = entradas_salvas
    saidas[fila_salva] = saidas_salvas
    print(f"Estado recuperado: {fila_salva}, {ocupacao_de(fila_salva)} pessoa(s)")
conectar(client, "processador")
threading.Thread(target=painel, daemon=True).start()
threading.Thread(target=retransmitir, args=(client,), daemon=True).start()
client.loop_forever()
if falhou:
    sys.exit("Processador parado: corrija o banco e inicie de novo; o broker reentrega o pendente.")
