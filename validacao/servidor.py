"""Interface local de validação de tickets, sem credenciais MQTT no navegador."""

import json
import sqlite3
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import paho.mqtt.client as mqtt

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from estado_filas import CAMINHO_PADRAO
from mqtt_config import conectar


estados = {}
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
        if self.path == "/":
            corpo = (Path(__file__).parent / "index.html").read_bytes()
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
