"""Teste de ponta a ponta: Wokwi, broker, processador, banco, backend com AWS e observabilidade.

Antes: `docker compose up -d --build` e as duas simulações abertas no VS Code
(Wokwi: Start Simulator em produtor/ e em produtor/consumidor/), com o firmware
atual (pio run -e sensores -e consumidor, em produtor/).

    .venv/bin/python tests/e2e_completo.py

Os rostos são gerados por IA (thispersondoesnotexist.com): ninguém real vai
para a coleção do Rekognition. Ficam em .local/e2e/rostos/ e as contas e2e-*
são reaproveitadas a cada execução; os ingressos são comprados de novo.

O teste aciona os sensores pela serial do produtor (RFC 2217, porta 4000),
lota a fila-a até ela fechar e desviar para a fila-b, manda dois clientes
para a fila-b, passa todos na catraca das duas filas (com o rosto conferido no Rekognition), confere a reação do ESP32
consumidor, repete o caso do 504 com o processador parado e esvazia a fila.
Tudo é observado pelo /admin/ao-vivo, o mesmo que o dashboard mostra.
"""

import base64
import json
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BACKEND = os.getenv("E2E_BACKEND", "http://127.0.0.1:8444")
PORTA_SERIAL_PRODUTOR = 4000
PASTA_ROSTOS = RAIZ / ".local" / "e2e" / "rostos"
SENHA = "e2e-senha-de-teste"  # contas só do ambiente de desenvolvimento
CLIENTES = [f"e2e-cliente-{n}" for n in range(1, 6)]
PESSOAS_NA_FILA = 5  # 5 x 7 s estimados por pessoa: acima do limite de bloqueio (30 s)


# ---------- HTTP ----------

def api(metodo, caminho, corpo=None, token=None, espera=30):
    pedido = urllib.request.Request(f"{BACKEND}{caminho}", method=metodo,
                                    data=json.dumps(corpo).encode() if corpo is not None else None)
    pedido.add_header("Content-Type", "application/json")
    if token:
        pedido.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(pedido, timeout=espera) as resposta:
            return resposta.status, json.load(resposta)
    except urllib.error.HTTPError as erro:
        with erro:
            return erro.code, json.loads(erro.read() or b"{}")


# ---------- pessoas ----------

def rosto(login):
    """Foto do rosto da conta; baixa um rosto gerado por IA na primeira vez."""
    arquivo = PASTA_ROSTOS / f"{login}.jpg"
    if not arquivo.exists():
        PASTA_ROSTOS.mkdir(parents=True, exist_ok=True)
        pedido = urllib.request.Request(f"https://thispersondoesnotexist.com/random-person.jpeg?{login}",
                                        headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(pedido, timeout=30) as resposta:
            foto = resposta.read()
        assert foto.startswith(b"\xff\xd8"), f"o site não devolveu um JPEG para {login}"
        arquivo.write_bytes(foto)
        time.sleep(1)  # o site gera um rosto novo por segundo
    return base64.b64encode(arquivo.read_bytes()).decode()


def conta(login, nome, papel="cliente"):
    """Entra com a conta e2e, criando-a (rosto no Rekognition) e definindo o papel se preciso."""
    status, sessao = api("POST", "/sessoes", {"login": login, "senha": SENHA})
    if status == 401:
        status, criado = api("POST", "/usuarios", {"login": login, "senha": SENHA, "nome": nome,
                                                    "foto": rosto(login)})
        assert status == 201, f"cadastro de {login}: {status} {criado}"
        print(f"  conta criada: {login}")
        status, sessao = api("POST", "/sessoes", {"login": login, "senha": SENHA})
    assert status == 200, f"login de {login}: {status} {sessao}"
    if sessao["papel"] != papel:
        subprocess.run([str(RAIZ / "banco" / "definir-papel.sh"), login, papel], check=True,
                       stdout=subprocess.DEVNULL)
        status, sessao = api("POST", "/sessoes", {"login": login, "senha": SENHA})
    return sessao["token"]


# ---------- Wokwi ----------

class SerialProdutor:
    """Serial do ESP32 dos sensores no Wokwi: envia comandos e guarda o que ele imprime."""

    def __init__(self):
        try:
            self.conexao = socket.create_connection(("127.0.0.1", PORTA_SERIAL_PRODUTOR), timeout=5)
        except OSError:
            raise SystemExit("Serial do Wokwi fora do ar (porta 4000): abra a simulação de produtor/ no "
                             "VS Code (Wokwi: Start Simulator).")
        self.conexao.settimeout(None)
        self.texto = ""
        threading.Thread(target=self._ler, daemon=True).start()

    def _ler(self):
        while dados := self.conexao.recv(4096):
            # Descarta a negociação telnet do RFC 2217; o firmware só imprime ASCII e UTF-8.
            self.texto += bytes(b for b in dados if b < 0xF0 or b > 0xFF).decode("utf-8", "replace")

    def pessoa(self, acao, fila):
        self.conexao.sendall(f"{acao} {fila}\n".encode())
        time.sleep(0.3)


# ---------- observação ----------

def esperar(descricao, condicao, token, limite=40):
    fim = time.time() + limite
    while True:
        _, estado = api("GET", "/admin/ao-vivo", token=token)
        if condicao(estado):
            print(f"  ok: {descricao}")
            return estado
        if time.time() > fim:
            raise AssertionError(f"{descricao}: não aconteceu em {limite} s.\n"
                                 f"{json.dumps(estado.get('filas'), indent=1, default=str)}")
        time.sleep(0.5)


def fila(estado, fila_id):
    return next((f for f in estado["filas"] if f["filaId"] == fila_id), {})


def ocupacao(estado, fila_id):
    return (fila(estado, fila_id).get("estado") or {}).get("ocupacao")


def semaforo(estado, fila_id):
    return (fila(estado, fila_id).get("estado") or {}).get("semaforo")


def online(estado, componente):
    return any(c["source"] == componente and c["online"] for c in estado["componentes"])


def passar_na_catraca(validador, admin, ingresso, login_do_rosto, esperado, motivo=None, fila_id="fila-a"):
    status, resposta = api("POST", "/leituras", {"ingressoId": ingresso, "filaId": fila_id,
                                                 "foto": rosto(login_do_rosto)}, validador)
    assert status == 200, f"leitura de {login_do_rosto}: {status} {resposta}"
    assert (resposta["resultado"], resposta.get("motivo")) == (esperado, motivo), resposta
    acao = {"aceito": "liberar", "recusado": "barrar", "indeterminado": "decidir-manual"}[esperado]
    resultado_id = f"{resposta['eventId']}-resultado"
    esperar(f"{login_do_rosto} na {fila_id}: {esperado}{f' ({motivo})' if motivo else ''}, "
            f"consumidor reagiu com {acao}",
            lambda e: (fila(e, fila_id).get("ultimaReacao") or {}).get("resultadoId") == resultado_id
            and fila(e, fila_id)["ultimaReacao"]["acao"] == acao, admin, limite=15)
    return resposta


def docker_compose(*argumentos):
    subprocess.run(["docker", "compose", "-f", str(RAIZ / "docker-compose.yml"), *argumentos],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------- roteiro ----------

def main():
    status, _ = api("GET", "/eu")
    assert status == 401, f"backend em {BACKEND} não respondeu como esperado ({status})"

    print("1. Contas (rostos gerados por IA, cadastrados no Rekognition pelo backend)")
    admin = conta("e2e-admin", "Admin E2E", "admin")
    validador = conta("e2e-validador", "Validador E2E", "validador")
    clientes = {login: conta(login, f"Cliente E2E {login[-1]}") for login in CLIENTES}

    print("2. Componentes no ar")
    for componente in ("produtor", "consumidor", "processador", "backend"):
        esperar(f"{componente} online", lambda e, c=componente: online(e, c), admin, limite=10)
    esperar("heartbeat das duas filas chegando do Wokwi",
            lambda e: all(fila(e, f).get("enlaceAtivo") for f in ("fila-a", "fila-b")), admin, limite=10)
    serial = SerialProdutor()

    print("3. Compra dos ingressos")
    ingressos = {}
    for login, token in clientes.items():
        status, compra = api("POST", "/ingressos", token=token)
        assert status == 201, compra
        ingressos[login] = compra["ingressoId"]
    print(f"  {len(ingressos)} ingressos comprados")

    print("4. Filas zeradas")
    _, agora = api("GET", "/admin/ao-vivo", token=admin)
    for fila_id in ("fila-a", "fila-b"):
        for _ in range(ocupacao(agora, fila_id) or 0):
            serial.pessoa("saida", fila_id)
        esperar(f"{fila_id} vazia", lambda e, f=fila_id: ocupacao(e, f) == 0, admin)

    print(f"5. Lotando a fila-a com {PESSOAS_NA_FILA} pessoas pelo sensor de entrada do Wokwi")
    for _ in range(PESSOAS_NA_FILA):
        serial.pessoa("chegada", "fila-a")
    assert "Chegada simulada na fila-a" in serial.texto, (
        "o produtor não reconheceu o comando da serial: recompile (pio run -e sensores) e reinicie a simulação")
    esperar(f"fila-a com {PESSOAS_NA_FILA} pessoas", lambda e: ocupacao(e, "fila-a") == PESSOAS_NA_FILA, admin)
    # Com passagens recentes na janela de 90 s, a vazão medida ainda é a antiga; ao saírem
    # da janela sem ninguém passar, a entrada conta como parada e a fila fecha.
    esperar("fila-a bloqueada e recomendando a fila-b",
            lambda e: semaforo(e, "fila-a") == "bloqueada"
            and fila(e, "fila-a")["recomendacao"]["sentidoRecomendado"] == "fila-b"
            and semaforo(e, "fila-b") == "livre", admin, limite=100)

    c1, c2, c3, c4, c5 = CLIENTES
    print(f"6. {c4} e {c5} seguem a recomendação e entram na fila-b")
    for _ in (c4, c5):
        serial.pessoa("chegada", "fila-b")
    esperar("fila-b com 2 pessoas", lambda e: ocupacao(e, "fila-b") == 2, admin)

    print("7. Catraca da fila-a: rosto no Rekognition, decisão no processador, reação no consumidor")
    passar_na_catraca(validador, admin, ingressos[c1], c1, "aceito")
    serial.pessoa("saida", "fila-a")
    passar_na_catraca(validador, admin, ingressos[c1], c1, "recusado", "ingresso-ja-usado")
    passar_na_catraca(validador, admin, ingressos[c2], c3, "recusado", "rosto-nao-confere")
    for login in (c2, c3):
        passar_na_catraca(validador, admin, ingressos[login], login, "aceito")
        serial.pessoa("saida", "fila-a")

    print("8. Catraca da fila-b")
    passar_na_catraca(validador, admin, ingressos[c4], c4, "aceito", fila_id="fila-b")
    serial.pessoa("saida", "fila-b")

    print("9. Processador fora do ar durante uma leitura na fila-b (o caso do 504)")
    _, antes = api("GET", "/admin/ao-vivo", token=admin)
    expiradas = antes["rejeitadas"].get("leitura-expirada", 0)
    docker_compose("stop", "processador")
    status, resposta = api("POST", "/leituras", {"ingressoId": ingressos[c5], "filaId": "fila-b",
                                                 "foto": rosto(c5)}, validador)
    assert status == 504, f"esperava 504 com o processador parado: {status} {resposta}"
    print("  ok: 504, decidir manualmente")
    docker_compose("start", "processador")
    esperar("processador de volta descartou a leitura vencida",
            lambda e: online(e, "processador")
            and e["rejeitadas"].get("leitura-expirada", 0) > expiradas, admin, limite=60)
    passar_na_catraca(validador, admin, ingressos[c5], c5, "aceito", fila_id="fila-b")
    serial.pessoa("saida", "fila-b")

    print("10. Esvaziando as filas")
    for _ in range(PESSOAS_NA_FILA - 3):  # quem ficou na fila-a sem ingresso no teste desiste e sai
        serial.pessoa("saida", "fila-a")
    for fila_id in ("fila-a", "fila-b"):
        esperar(f"{fila_id} vazia e livre",
                lambda e, f=fila_id: ocupacao(e, f) == 0 and semaforo(e, f) == "livre", admin)

    entradas = {c1: "fila-a", c2: "fila-a", c3: "fila-a", c4: "fila-b", c5: "fila-b"}
    for login, token in clientes.items():
        _, meus = api("GET", "/ingressos", token=token)
        usado = next(i for i in meus if i["ingressoId"] == ingressos[login])
        assert usado["usadoEm"] and usado["filaEntrada"] == entradas[login], (login, usado)
    _, resumo = api("GET", "/admin/resumo", token=admin)
    print(f"\nTudo certo. Leituras: {resumo['leituras']}; ingressos: {resumo['ingressos']}")


if __name__ == "__main__":
    main()
