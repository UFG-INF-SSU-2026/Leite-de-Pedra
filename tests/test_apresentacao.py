"""Catraca da apresentação: o backend publica a leitura e o processador real decide.

O Rekognition entra como o dobro que o backend já usa nos outros testes. O que
não é dobrado é a decisão: a mensagem publicada em POST /leituras passa pelo
processador e pelo banco filas_teste, como no dia em que a AWS e o broker estão no ar.
"""

import json
import runpy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import estado_filas
import mqtt_config
from apoio_backend import carregar_backend, foto, rekognition, s3
from apoio_banco import cadastrar, motor_teste
from modelos import Ingresso, Usuario
from senhas import gerar_hash_senha


class FilaDoBroker:
    """O papel do Mosquitto neste teste: guarda a leitura e, se o processador estiver no ar, entrega."""

    def __init__(self, processador, no_ar):
        self.processador = processador
        self.no_ar = no_ar
        self.cliente = ClienteDoProcessador()
        self.retidas = []

    def publish(self, topico, conteudo, qos=1):
        self.retidas.append((topico, conteudo))
        if self.no_ar:
            self.entregar(topico, conteudo)
        return SimpleNamespace(rc=0, mid=1)

    def entregar(self, topico, conteudo):
        bruto = conteudo.encode() if isinstance(conteudo, str) else conteudo
        self.processador["on_message"](
            self.cliente, None, SimpleNamespace(topic=topico, payload=bruto, mid="1", qos=1))
        app = carregar_backend()
        for topico_saida, corpo, _ in self.cliente.publicacoes:
            if str(topico_saida).endswith("/resultado"):
                app.receber_resultado(corpo)


class ClienteDoProcessador:
    def __init__(self):
        self.publicacoes = []

    def publish(self, topico, payload, **_):
        self.publicacoes.append((topico, json.loads(payload), _))
        return SimpleNamespace(rc=0, mid=len(self.publicacoes))

    def ack(self, mid, qos):
        pass


def subir_processador():
    original = estado_filas.EstadoFilas
    with patch.object(estado_filas, "EstadoFilas", side_effect=lambda: original(motor_teste())), \
         patch.object(mqtt_config, "conectar"), \
         patch("threading.Thread.start"), \
         patch("paho.mqtt.client.Client.loop_forever"):
        return runpy.run_path("processador/processador.py")


class ApresentacaoTest(unittest.TestCase):
    def setUp(self):
        self.app = carregar_backend()
        rekognition.rostos.clear()
        s3.limpar()
        self.processador = subir_processador()
        self.api = TestClient(self.app.app)
        self.api.__enter__()
        cadastro = {"login": "ana", "senha": "senha-da-ana", "nome": "Ana", "foto": foto("ana")}
        self.assertEqual(self.api.post("/usuarios", json=cadastro).status_code, 201)
        ana = self.api.post("/sessoes", json={"login": "ana", "senha": "senha-da-ana"}).json()
        self.ana = {"Authorization": f"Bearer {ana['token']}"}
        cadastrar(self.processador["estado_persistente"].motor, Usuario(
            usuario_id="validador-1", login="vera", nome="Vera",
            senha_hash=gerar_hash_senha("senha-da-vera"), face_id="f-vera", papel="validador"))
        vera = self.api.post("/sessoes", json={"login": "vera", "senha": "senha-da-vera"}).json()
        self.vera = {"Authorization": f"Bearer {vera['token']}"}

    def tearDown(self):
        self.app.ESPERA_RESULTADO_SEGUNDOS = 10
        self.api.__exit__(None, None, None)

    def ler(self, broker):
        ingresso = self.api.post("/ingressos", headers=self.ana).json()["ingressoId"]
        with patch.object(self.app.cliente_mqtt, "is_connected", return_value=True), \
             patch.object(self.app.cliente_mqtt, "publish", broker.publish):
            resposta = self.api.post(
                "/leituras",
                json={"ingressoId": ingresso, "filaId": "fila-a", "foto": foto("ana")},
                headers=self.vera)
        return ingresso, resposta

    def test_processador_no_ar_libera_o_dono(self):
        ingresso, resposta = self.ler(FilaDoBroker(self.processador, no_ar=True))
        self.assertEqual(resposta.status_code, 200, resposta.text)
        corpo = resposta.json()
        self.assertEqual(corpo["resultado"], "aceito")
        self.assertEqual(corpo["pessoa"], {"nome": "Ana", "login": "ana"})
        with self.processador["estado_persistente"].sessao() as s:
            self.assertIsNotNone(s.get(Ingresso, ingresso).usado_em)

    def test_processador_fora_nao_gasta_o_ingresso(self):
        """Na apresentação o processador ainda está subindo. A catraca não pode queimar o QR."""
        broker = FilaDoBroker(self.processador, no_ar=False)
        self.app.ESPERA_RESULTADO_SEGUNDOS = 0.2
        ingresso, resposta = self.ler(broker)
        self.assertEqual(resposta.status_code, 504, resposta.text)
        # O broker reentrega quando o processador volta, como a sessão persistente faz.
        topico, conteudo = broker.retidas[0]
        broker.no_ar = True
        broker.entregar(topico, conteudo)
        de_novo = FilaDoBroker(self.processador, no_ar=True)
        with patch.object(self.app.cliente_mqtt, "is_connected", return_value=True), \
             patch.object(self.app.cliente_mqtt, "publish", de_novo.publish):
            retry = self.api.post(
                "/leituras",
                json={"ingressoId": ingresso, "filaId": "fila-a", "foto": foto("ana")},
                headers=self.vera)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(retry.json()["resultado"], "aceito")
