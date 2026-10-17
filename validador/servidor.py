"""Interface local de validação de tickets, sem credenciais MQTT no navegador."""

import json
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import paho.mqtt.client as mqtt

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from estado_filas import CAMINHO_PADRAO
from mqtt_config import conectar


PASTA_LOGS = RAIZ / ".local" / "logs"
# Um log sem linhas novas não prova que o processo parou (broker ocioso não
# escreve nada); por isso o painel consulta o processo pelo comando.
TERMINAIS = {
    "broker": "mosquitto -c broker/mosquitto.conf",
    "processador": "processador/processador.py",
    "observador": "observador/observador.py",
    "validador": None,  # é este próprio processo
}
# Exibido ao lado do nome; "→" indica cliente que só se conecta ao broker.
PORTAS_TERMINAIS = {
    "broker": "8883",
    "processador": "→ 8883",
    "observador": "→ 8883",
    "validador": "8000",
}
# Portas definidas por rfc2217ServerPort nos wokwi.toml.
PORTAS_WOKWI = {
    "wokwi-sensores": 4000,
    "wokwi-sinalizador": 4001,
    "wokwi-intruso": 4005,  # firmware sem a senha, para demonstrar a recusa
}
LINHAS = 200
PAGINAS = {
    "/": Path(__file__).parent / "index.html",
    # Mesma origem da API: a apresentação lê os logs sem precisar liberar CORS.
    "/apresentacao": RAIZ / "entregas" / "Marco3" / "apresentacao-seguranca.html",
}

estados = {}
seriais = {nome: deque(maxlen=LINHAS) for nome in PORTAS_WOKWI}
serial_conectada = {nome: False for nome in PORTAS_WOKWI}
serial_atualizada = {nome: None for nome in PORTAS_WOKWI}
trava_estados = threading.Lock()
cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)


def ao_conectar(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        client.subscribe("fila/+/estado", qos=1)
        print("Validador conectado ao broker MQTT/TLS")
    else:
        print(f"Falha na autenticação MQTT: {reason_code}")


def ao_receber(client, userdata, mensagem):
    try:
        payload = json.loads(mensagem.payload)
        fila = payload["filaId"]
    except (ValueError, KeyError, TypeError):
        return
    if fila not in {"fila-a", "fila-b"}:
        return
    with trava_estados:
        estados[fila] = payload


def sem_telnet(dados):
    """Remove os comandos Telnet do RFC 2217 e deixa só o texto da serial."""
    # ponytail: ignora comando cortado entre dois recv; no pior caso some um byte do log.
    saida = bytearray()
    i = 0
    while i < len(dados):
        byte = dados[i]
        if byte != 255:
            saida.append(byte)
            i += 1
        elif i + 1 < len(dados) and dados[i + 1] == 255:
            saida.append(255)
            i += 2
        elif i + 1 < len(dados) and dados[i + 1] == 250:
            fim = dados.find(bytes([255, 240]), i + 2)
            i = len(dados) if fim < 0 else fim + 2
        elif i + 1 < len(dados) and 251 <= dados[i + 1] <= 254:
            i += 3
        else:
            i += 2
    return bytes(saida)


def ler_serial(nome, porta):
    linhas = seriais[nome]
    while True:
        try:
            with socket.create_connection(("127.0.0.1", porta), timeout=5) as conexao:
                conexao.settimeout(None)
                serial_conectada[nome] = True
                linhas.append(f"[conectado à serial do Wokwi na porta {porta}]")
                resto = ""
                while dados := conexao.recv(4096):
                    serial_atualizada[nome] = time.time()
                    texto = resto + sem_telnet(dados).decode("utf-8", "replace")
                    *completas, resto = texto.replace("\r", "").split("\n")
                    linhas.extend(completas)
            linhas.append("[simulação encerrada]")
        except OSError:
            pass
        serial_conectada[nome] = False
        time.sleep(2)


def processo_ativo(comando):
    if comando is None:
        return True
    return subprocess.run(["pgrep", "-f", comando], capture_output=True).returncode == 0


def log_terminal(nome, comando):
    caminho = PASTA_LOGS / f"{nome}.log"
    try:
        with open(caminho, encoding="utf-8", errors="replace") as arquivo:
            linhas = [linha.rstrip("\n") for linha in deque(arquivo, LINHAS)]
        atualizado = caminho.stat().st_mtime
    except FileNotFoundError:
        linhas = [f"Sem log. Inicie com: ... 2>&1 | tee .local/logs/{nome}.log"]
        atualizado = None
    return {
        "linhas": linhas,
        "rodando": processo_ativo(comando),
        "atualizadoEm": atualizado,
        "porta": PORTAS_TERMINAIS[nome],
    }


cliente.on_connect = ao_conectar
cliente.on_message = ao_receber


def ocupacao(fila):
    if not CAMINHO_PADRAO.exists():
        return 0
    with sqlite3.connect(CAMINHO_PADRAO) as conexao:
        linha = conexao.execute(
            "SELECT entradas - saidas FROM filas WHERE fila_id = ?", (fila,)
        ).fetchone()
    return linha[0] if linha else 0


def resumo_fila(fila, estados_recebidos):
    saldo = ocupacao(fila)
    estado = estados_recebidos.get(fila)
    # Retain do broker pode ter sido publicado com outro banco de demonstração.
    if estado and estado.get("ocupacao") != saldo:
        estado = None
    return {"ocupacao": saldo, "estado": estado}


class Handler(BaseHTTPRequestHandler):
    def responder_json(self, codigo, dados):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        if self.path in PAGINAS:
            corpo = PAGINAS[self.path].read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
        elif self.path == "/api/filas":
            with trava_estados:
                copia = dict(estados)
            self.responder_json(200, {
                fila: resumo_fila(fila, copia)
                for fila in ("fila-a", "fila-b")
            })
        elif self.path == "/api/logs":
            logs = {nome: log_terminal(nome, comando) for nome, comando in TERMINAIS.items()}
            for nome, linhas in seriais.items():
                logs[nome] = {
                    "linhas": list(linhas) or [
                        "Aguardando a simulação (rfc2217ServerPort no wokwi.toml)"
                    ],
                    "rodando": serial_conectada[nome],
                    "atualizadoEm": serial_atualizada[nome],
                    "porta": f"serial {PORTAS_WOKWI[nome]}",
                }
            self.responder_json(200, logs)
        else:
            self.responder_json(404, {"erro": "Não encontrado"})

    def do_POST(self):
        if self.path != "/api/validacoes":
            self.responder_json(404, {"erro": "Não encontrado"})
            return
        try:
            tamanho = int(self.headers.get("Content-Length", "0"))
            if not 0 < tamanho <= 1024:
                raise ValueError("Tamanho inválido")
            dados = json.loads(self.rfile.read(tamanho))
            fila = dados["filaId"]
            if fila not in {"fila-a", "fila-b"}:
                raise ValueError("Fila inválida")
        except (ValueError, KeyError, TypeError):
            self.responder_json(400, {"erro": "Informe fila-a ou fila-b"})
            return

        if ocupacao(fila) == 0:
            self.responder_json(409, {"erro": "Não há pessoa aguardando nessa fila"})
            return
        if not cliente.is_connected():
            self.responder_json(503, {"erro": "Broker MQTT indisponível"})
            return

        payload = {
            "eventId": uuid.uuid4().hex,
            "filaId": fila,
            "tipo": "validacao",
            "resultado": "aprovado",
            "eventTimeMs": int(time.time() * 1000),
        }
        publicacao = cliente.publish(
            f"fila/{fila}/validacao", json.dumps(payload), qos=1
        )
        try:
            publicacao.wait_for_publish(timeout=3)
        except RuntimeError:
            pass
        if publicacao.rc != mqtt.MQTT_ERR_SUCCESS or not publicacao.is_published():
            self.responder_json(503, {"erro": "Falha ao enviar validação"})
            return
        self.responder_json(202, {"mensagem": f"Ticket validado na {fila}"})


if __name__ == "__main__":
    # A página continua disponível mesmo se o broker ainda não subiu;
    # o Paho reconecta em segundo plano assim que ele estiver acessível.
    conectar(cliente, "validador", assincrono=True)
    cliente.loop_start()
    for nome, porta in PORTAS_WOKWI.items():
        threading.Thread(target=ler_serial, args=(nome, porta), daemon=True).start()
    servidor = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("Validador disponível em http://localhost:8000")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
        cliente.disconnect()
        cliente.loop_stop()
