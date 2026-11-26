"""Testes unitários do processador, com o banco (EstadoFilas) e o broker falsos."""

import json
import runpy
import time
import unittest
from collections import deque
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy.exc import DBAPIError

import estado_filas
import mqtt_config
from mqtt_config import evento, ler_evento


class Parar(Exception):
    """Interrompe os laços infinitos (painel, retransmitir) depois de uma volta."""


def erro_de_banco():
    return DBAPIError("SELECT 1", {}, Exception("banco fora"))


class ProcessadorTest(unittest.TestCase):
    def setUp(self):
        with patch.object(estado_filas, "EstadoFilas") as classe, \
             patch.object(mqtt_config, "conectar"), \
             patch.object(mqtt_config, "desconectar"), \
             patch("threading.Thread.start"), \
             patch("paho.mqtt.client.Client.loop_forever"):
            classe.return_value.listar.return_value = []
            # run_path devolve uma cópia; o dicionário vivo é o das funções.
            self.p = runpy.run_path("processador/processador.py")["registrar"].__globals__
        self.estado = self.p["estado_persistente"]
        self.estado.saida_pendente.return_value = []
        self.cliente = MagicMock()
        self.cliente.publish.return_value = SimpleNamespace(rc=0, mid=1)
        self.print = patch("builtins.print").start()
        self.addCleanup(patch.stopall)

    def publicadas(self, topico=None):
        return [(c.args[0], json.loads(c.args[1])) for c in self.cliente.publish.call_args_list
                if topico is None or c.args[0] == topico]

    def mensagem(self, tipo, payload, fila="fila-a", **campos):
        conteudo = json.dumps(evento(tipo, "produtor", {"filaId": fila, **payload}, **campos))
        return SimpleNamespace(topic=f"fila/{fila}/{tipo}", payload=conteudo.encode(), mid=7, qos=1)

    def leitura(self, **mudancas):
        payload = {"fotoRef": "leituras/1.jpg", "ingressoId": "ING", "validadorId": "v1",
                   "reconhecimento": "reconhecido", "usuarioReconhecido": "u1",
                   "validoAte": int((time.time() + 60) * 1000), **mudancas}
        return self.mensagem("leitura", {k: v for k, v in payload.items() if v is not None})

    def com_heartbeat(self, *filas):
        for fila in filas:
            self.p["registrar"](fila)
            self.p["ultimo_heartbeat_recebido"][fila] = time.monotonic()

    def motivos_rejeitados(self):
        return [m["payload"]["motivo"] for _, m in self.publicadas(self.p["TOPICO_REJEITADO"])]

    # ---------- descoberta e mensagens ----------

    def test_registrar(self):
        self.p["registrar"]("fila-b")
        self.p["registrar"]("fila-a")
        self.p["entradas"]["fila-a"] = 3
        self.p["registrar"]("fila-a")  # de novo: não zera
        self.assertEqual(self.p["filas"], ["fila-a", "fila-b"])
        self.assertEqual((self.p["entradas"]["fila-a"], self.p["semaforo"]["fila-b"]), (3, "livre"))

    def test_on_message(self):
        self.p["on_message"](self.cliente, None, SimpleNamespace(topic="fila/fila-a/contagem", payload=b"x",
                                                                 mid=3, qos=1))
        self.cliente.ack.assert_called_once_with(3, 1)

        self.estado.aplicar.side_effect = erro_de_banco()
        self.p["on_message"](self.cliente, None, self.mensagem("contagem", {}))
        self.assertEqual(self.cliente.ack.call_count, 1)  # sem ack: o broker reentrega
        self.assertTrue(self.p["falhou"])
        self.p["desconectar"].assert_called_once_with(self.cliente, "processador")

    def test_desconectar_sem_confirmar(self):
        self.p["desconectar_sem_confirmar"](self.cliente, erro_de_banco())
        self.assertTrue(self.p["falhou"])
        self.p["desconectar"].assert_called_once()

    def test_rejeitar(self):
        lixo = SimpleNamespace(topic="fila/fila-a/contagem", payload=b"lixo")
        self.assertTrue(self.p["rejeitar"](self.cliente, lixo, "fora-do-contrato"))
        topico, rejeicao = self.publicadas()[0]
        self.assertEqual(ler_evento(topico, json.dumps(rejeicao)), rejeicao)
        self.assertEqual(rejeicao["payload"]["conteudo"], "lixo")

        self.p["rejeitar"](self.cliente, SimpleNamespace(topic="fila/fila-a/leitura", payload=b"foto"), "x")
        self.assertNotIn("conteudo", self.publicadas()[1][1]["payload"])  # leitura não vaza

        recebido = evento("contagem", "produtor", {}, correlation_id="c1", event_id="e1")
        self.p["rejeitar"](self.cliente, lixo, "duplicado", recebido)
        rejeicao = self.publicadas()[2][1]
        self.assertEqual((rejeicao["payload"]["eventId"], rejeicao["correlation_id"]), ("e1", "c1"))
        self.assertNotIn("conteudo", rejeicao["payload"])

    def test_processar_mensagem_movimentos(self):
        self.estado.aplicar.return_value = (True, 1, 0)
        self.assertTrue(self.p["processar_mensagem"](self.cliente, self.mensagem("contagem", {})))
        self.assertEqual(self.p["entradas"]["fila-a"], 1)

        self.estado.aplicar.return_value = (True, 1, 1)
        self.p["processar_mensagem"](self.cliente, self.mensagem("saida", {}))
        self.assertEqual(self.p["fila_saidas"]["fila-a"][-1][1], 0)  # quantos ficaram

        self.estado.aplicar.return_value = (False, 1, 1)
        self.p["processar_mensagem"](self.cliente, self.mensagem("saida", {}))
        self.assertEqual(len(self.p["fila_saidas"]["fila-a"]), 1)

        self.p["processar_mensagem"](self.cliente, self.mensagem("heartbeat", {}))
        self.assertIsNotNone(self.p["ultimo_heartbeat_recebido"]["fila-a"])
        self.p["processar_mensagem"](self.cliente, self.mensagem("estado", {}))
        self.assertEqual(self.motivos_rejeitados(), ["duplicado", "tipo-desconhecido"])

    def test_processar_mensagem_leituras(self):
        self.estado.registrar_resultado.return_value = ("aceito", None, 1, True)
        self.assertTrue(self.p["processar_mensagem"](self.cliente, self.leitura()))
        self.estado.registrar_resultado.assert_called_once()

        self.estado.registrar_resultado.return_value = ("aceito", None, 1, False)
        self.p["processar_mensagem"](self.cliente, self.leitura())
        for incompleta in ({"fotoRef": ""}, {"reconhecimento": "talvez"}, {"validoAte": "logo"},
                           {"usuarioReconhecido": None}, {"reconhecimento": "falha"}):
            self.p["processar_mensagem"](self.cliente, self.leitura(**incompleta))
        self.p["processar_mensagem"](self.cliente, self.leitura(validoAte=1))
        self.assertEqual(self.motivos_rejeitados(), ["duplicado"] + ["leitura-incompleta"] * 5
                         + ["leitura-expirada"])
        self.assertEqual(self.estado.registrar_resultado.call_count, 2)
        self.assertEqual(self.p["filas"], [])  # leitura não cria fila

    def test_texto_valido(self):
        for valido in ("a", "a" * 256):
            self.assertTrue(self.p["texto_valido"](valido))
        for invalido in ("", "a" * 257, 5, None):
            self.assertFalse(self.p["texto_valido"](invalido), invalido)

    # ---------- leituras e saída (outbox) ----------

    def test_resultado_de(self):
        leitura = evento("leitura", "backend", {"filaId": "fila-a", "ingressoId": "ING"},
                         correlation_id="c1", event_id="L1")
        evento_id, topico, conteudo = self.p["resultado_de"](leitura)("recusado", "rosto-nao-confere", 123)
        resultado = json.loads(conteudo)
        self.assertEqual(ler_evento(topico, conteudo), resultado)
        self.assertEqual((evento_id, topico, resultado["correlation_id"], resultado["timestamp"]),
                         ("L1-resultado", "fila/fila-a/resultado", "c1", 123))
        self.assertEqual(resultado["payload"], {"filaId": "fila-a", "leituraId": "L1", "ingressoId": "ING",
                                                "resultado": "recusado", "motivo": "rosto-nao-confere"})
        self.assertNotIn("motivo", json.loads(self.p["resultado_de"](leitura)("aceito", None, 1)[2])["payload"])

    def test_decidir_leitura(self):
        self.estado.registrar_resultado.return_value = ("aceito", None, 1, True)
        casos = ((False, "reconhecido", ("recusado", "validador-nao-autorizado")),
                 (True, "falha", ("indeterminado", "falha-reconhecimento")),
                 (True, "nao-reconhecido", ("recusado", "rosto-nao-confere")),
                 (True, "reconhecido", ("aceito", None)))
        for validador, reconhecimento, decisao in casos:
            self.estado.e_validador.return_value = validador
            leitura = evento("leitura", "backend", {"filaId": "fila-a", "ingressoId": "ING", "validadorId": "v1",
                                                    "reconhecimento": reconhecimento, "usuarioReconhecido": "u1"})
            self.assertTrue(self.p["decidir_leitura"](self.cliente, leitura))
            self.assertEqual(self.estado.registrar_resultado.call_args.args[4:6], decisao, reconhecimento)
        self.assertEqual(self.estado.saida_pendente.call_count, 4)  # publica a saída a cada decisão

    def test_publicar_saida(self):
        self.estado.saida_pendente.return_value = [("e1", "t", "c"), ("e2", "t", "c"), ("e3", "t", "c")]
        self.p["aguardando_puback"][99] = "e1"  # no ar, sem PUBACK: não sai de novo
        self.cliente.publish.side_effect = [SimpleNamespace(rc=0, mid=5), SimpleNamespace(rc=4, mid=6)]
        self.p["publicar_saida"](self.cliente)
        self.assertEqual(self.cliente.publish.call_count, 2)
        self.assertEqual(self.p["aguardando_puback"], {99: "e1", 5: "e2"})

    def test_on_publish(self):
        self.p["aguardando_puback"].update({5: "e2", 6: "e3"})
        self.p["on_publish"](self.cliente, None, 5, 0, None)
        self.p["on_publish"](self.cliente, None, 42, 0, None)  # mid que não é da saída
        self.estado.marcar_publicado.assert_called_once_with("e2")
        self.estado.marcar_publicado.side_effect = erro_de_banco()
        self.p["on_publish"](self.cliente, None, 6, 0, None)  # não propaga: sai de novo depois
        self.assertEqual(self.p["aguardando_puback"], {})

    def test_retransmitir(self):
        self.cliente.is_connected.side_effect = [False, True, True]
        self.estado.saida_pendente.side_effect = [erro_de_banco(), []]
        with patch("time.sleep", side_effect=[None, None, None, Parar]), self.assertRaises(Parar):
            self.p["retransmitir"](self.cliente)
        self.assertEqual(self.estado.saida_pendente.call_count, 2)

    # ---------- cálculo da fila ----------

    def test_heartbeat_recente(self):
        self.p["registrar"]("fila-a")
        self.assertFalse(self.p["heartbeat_recente"]("fila-a", 100))
        self.p["ultimo_heartbeat_recebido"]["fila-a"] = 100
        self.assertTrue(self.p["heartbeat_recente"]("fila-a", 115))
        self.assertFalse(self.p["heartbeat_recente"]("fila-a", 115.1))

    def test_ocupacao_de(self):
        self.p["registrar"]("fila-a")
        self.p["entradas"]["fila-a"], self.p["saidas"]["fila-a"] = 5, 2
        self.assertEqual(self.p["ocupacao_de"]("fila-a"), 3)
        self.p["saidas"]["fila-a"] = 9  # sensor de saída contou a mais
        self.assertEqual(self.p["ocupacao_de"]("fila-a"), 0)

    def passagens(self, *segundos_e_restantes):
        agora = datetime.now()
        self.p["registrar"]("fila-a")
        self.p["fila_saidas"]["fila-a"] = deque(
            (agora - timedelta(seconds=s), restantes) for s, restantes in segundos_e_restantes)
        return agora

    def test_passagens_recentes(self):
        agora = self.passagens((100, 1), (10, 0))
        self.assertEqual([p[1] for p in self.p["passagens_recentes"]("fila-a", agora)], [0])

    def test_vazao_de(self):
        self.assertEqual(self.p["vazao_de"]("fila-a", self.passagens((10, 1))), 0)
        self.assertEqual(self.p["vazao_de"]("fila-a", self.passagens((12, 2), (8, 1), (4, 0))), 0.25)
        self.assertEqual(self.p["vazao_de"]("fila-a", self.passagens((12, 0), (2, 0))), 0)  # fila vazia

    def test_rajada_de_saidas_atrasadas_nao_zera_a_espera(self):
        # Depois de uma queda, as saídas guardadas chegam com milissegundos de diferença.
        agora = self.passagens(*[(i * 0.002, 15 + i) for i in range(4, -1, -1)])
        self.p["entradas"]["fila-a"], self.p["saidas"]["fila-a"] = 20, 5
        self.assertEqual(self.p["vazao_de"]("fila-a", agora), 0)
        self.assertEqual(self.p["espera_de"]("fila-a", agora), 15 * self.p["TEMPO_PASSAGEM_INICIAL"])

    def test_espera_de(self):
        agora = self.passagens()
        self.assertEqual(self.p["espera_de"]("fila-a", agora), 0)
        self.p["entradas"]["fila-a"] = 3
        self.assertEqual(self.p["espera_de"]("fila-a", agora), 3 * self.p["TEMPO_PASSAGEM_INICIAL"])
        self.assertEqual(self.p["espera_de"]("fila-a", self.passagens((200, 3))), float("inf"))  # parada
        self.assertEqual(self.p["espera_de"]("fila-a", self.passagens((5, 3))), 3 * 7)  # sem vazão ainda
        self.assertEqual(self.p["espera_de"]("fila-a", self.passagens((8, 4), (4, 3))), 12)

    def test_classificar(self):
        self.p["registrar"]("fila-a")
        casos = {"livre": ((15, "livre"), (16, "atencao"), (31, "bloqueada")),
                 "atencao": ((9, "atencao"), (8, "livre"), (30, "atencao"), (31, "bloqueada")),
                 "bloqueada": ((24, "bloqueada"), (23, "atencao"), (8, "livre"))}
        for atual, esperas in casos.items():
            self.p["semaforo"]["fila-a"] = atual
            self.assertEqual(self.p["classificar"]("fila-a", None), atual)
            for espera, esperado in esperas:
                self.assertEqual(self.p["classificar"]("fila-a", espera), esperado, (atual, espera))

    def test_melhor_fila(self):
        self.p["semaforo"].update({"a": "bloqueada", "b": "atencao", "c": "livre", "d": "bloqueada"})
        self.assertEqual(self.p["melhor_fila"]("a", ["a", "b", "c", "d"], {"b": 20, "c": None}), "b")
        self.assertEqual(self.p["melhor_fila"]("a", ["a", "b", "c"], {"b": 20, "c": 5}), "c")
        self.assertEqual(self.p["melhor_fila"]("a", ["a", "d"], {}), "a")

    def test_espera_texto(self):
        self.assertEqual(self.p["espera_texto"](None), "espera indeterminada")
        self.assertEqual(self.p["espera_texto"](float("inf")), "espera indeterminada")
        self.assertEqual(self.p["espera_texto"](12.9), "12s de espera")

    def test_situacao_de(self):
        self.p["semaforo"]["fila-a"] = "atencao"
        self.assertEqual(self.p["situacao_de"]("fila-a", {"fila-a": 3}, {"fila-a": 20}),
                         "fila-a está AMARELO (20s de espera, 3 na fila)")

    def test_motivo_de(self):
        self.p["semaforo"].update({"a": "livre", "b": "bloqueada", "c": "livre"})
        ocupacao, espera = {"a": 1, "b": 9, "c": 0}, {"a": 5, "b": 40, "c": 0}
        self.assertTrue(self.p["motivo_de"]("a", "a", ocupacao, espera).endswith("sem motivo para desviar"))
        self.assertIn("nenhuma outra fila", self.p["motivo_de"]("b", "b", ocupacao, espera))
        self.assertEqual(self.p["motivo_de"]("b", "c", ocupacao, espera),
                         "b está VERMELHO (40s de espera, 9 na fila); c está VERDE (0s de espera, 0 na fila)")

    # ---------- publicação ----------

    def test_recomendar_fila(self):
        self.com_heartbeat("fila-a")
        self.p["registrar"]("fila-b")  # sem heartbeat: não publica
        self.p["entradas"]["fila-a"] = 6
        self.p["recomendar_fila"](self.cliente, "c1")
        self.assertEqual(sorted(t for t, _ in self.publicadas()), ["fila/fila-a/estado", "fila/fila-a/recomendacao"])
        self.assertEqual(self.p["semaforo"]["fila-a"], "bloqueada")  # 6 x 7 s = 42 s
        self.assertTrue(all(m["correlation_id"] == "c1" for _, m in self.publicadas()))

    def test_recomendar_fila_desvia_para_a_melhor(self):
        self.com_heartbeat("fila-a", "fila-b")
        self.p["entradas"]["fila-a"] = 6
        self.p["recomendar_fila"](self.cliente, "c1")
        destinos = {m["payload"]["filaId"]: m["payload"]["sentidoRecomendado"]
                    for _, m in self.publicadas() if m["event_type"] == "recomendacao"}
        self.assertEqual(destinos, {"fila-a": "fila-b", "fila-b": "fila-b"})

    def test_publicar_estado(self):
        self.p["registrar"]("fila-a")
        self.p["publicar_estado"](self.cliente, "fila-a", 2, "fila-a", 14.7, "c1")
        self.p["publicar_estado"](self.cliente, "fila-a", 2, "fila-a", 14.2, "c2")  # mesmo estado: não repete
        (topico, estado), = self.publicadas()
        self.assertEqual(ler_evento(topico, json.dumps(estado)), estado)
        self.assertEqual(estado["payload"]["tempoEsperaEstimado"], 14)
        self.assertTrue(self.cliente.publish.call_args.kwargs["retain"])
        self.estado.registrar_estado.assert_called_once_with("fila-a", "livre", 2, 14)

        self.cliente.publish.return_value = SimpleNamespace(rc=4, mid=2)  # falhou: tenta de novo depois
        self.p["publicar_estado"](self.cliente, "fila-a", 3, "fila-a", float("inf"), "c3")
        self.p["publicar_estado"](self.cliente, "fila-a", 3, "fila-a", float("inf"), "c3")
        self.assertIsNone(self.publicadas()[-1][1]["payload"]["tempoEsperaEstimado"])
        self.assertEqual(self.cliente.publish.call_count, 3)

    def test_publicar(self):
        self.p["registrar"]("fila-a")
        self.p["publicar"](self.cliente, "fila-a", 2, "fila-a", 3.9, "motivo", "c1")
        self.p["publicar"](self.cliente, "fila-a", 5, "fila-a", 30, "outro", "c2")  # mesmo semáforo e destino
        self.p["semaforo"]["fila-a"] = "atencao"
        self.p["publicar"](self.cliente, "fila-a", 5, "fila-b", None, "cheia", "c3")
        recomendacoes = [m["payload"] for _, m in self.publicadas("fila/fila-a/recomendacao")]
        self.assertEqual([(r["semaforo"], r["sentidoRecomendado"], r["tempoEsperaEstimado"]) for r in recomendacoes],
                         [("livre", "fila-a", 3), ("atencao", "fila-b", None)])
        self.assertEqual(self.p["ultima_publicacao"]["fila-a"], ("atencao", "fila-b"))

    def test_painel(self):
        self.com_heartbeat("fila-b")
        self.p["registrar"]("fila-a")
        self.p["ultima_publicacao"]["fila-b"] = ("livre", "fila-c")
        with patch("time.sleep", side_effect=[None, Parar]), self.assertRaises(Parar):
            self.p["painel"]()
        linhas = self.print.call_args.args[0].splitlines()
        self.assertIn("sem dados", linhas[0])
        self.assertIn("--> fila-c", linhas[1])

    def test_on_connect(self):
        self.p["on_connect"](self.cliente, None, None, 5, None)
        self.cliente.subscribe.assert_not_called()

        self.com_heartbeat("fila-a")
        self.p["ultima_publicacao"]["fila-a"] = ("livre", "fila-a")
        self.p["aguardando_puback"][1] = "e1"
        self.estado.saida_pendente.side_effect = erro_de_banco()  # não derruba: retransmitir tenta depois
        self.p["on_connect"](self.cliente, None, None, 0, None)
        self.assertEqual(len(self.cliente.subscribe.call_args.args[0]), 4)
        self.assertEqual((self.p["ultima_publicacao"]["fila-a"], self.p["ultimo_heartbeat_recebido"]["fila-a"],
                          self.p["aguardando_puback"]), (None, None, {}))


if __name__ == "__main__":
    unittest.main()
