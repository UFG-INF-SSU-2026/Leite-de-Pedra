"""Processador: o relógio simulado não decide o enlace; leituras, outbox e rejeitadas."""

import json
import runpy
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import estado_filas
import mqtt_config
from apoio_banco import cadastrar, motor_teste
from modelos import Ingresso, Usuario


class ClienteFalso:
    def __init__(self):
        self.publicacoes = []
        self.confirmadas = []

    def publish(self, topico, payload, **opcoes):
        self.publicacoes.append((topico, json.loads(payload), opcoes))
        return SimpleNamespace(rc=0, mid=len(self.publicacoes))  # mid = posição em publicacoes

    def ack(self, mid, qos):
        self.confirmadas.append(mid)


class HeartbeatTest(unittest.TestCase):
    def test_horario_antigo_do_esp_nao_bloqueia_estado(self):
        estado_original = estado_filas.EstadoFilas
        with patch.object(estado_filas, "EstadoFilas",
                          side_effect=lambda: estado_original(motor_teste())), \
             patch.object(mqtt_config, "conectar"), \
             patch("threading.Thread.start"), \
             patch("paho.mqtt.client.Client.loop_forever"):
            modulo = runpy.run_path("processador/processador.py")

        cliente = ClienteFalso()
        horario_antigo = int((time.time() - 120) * 1000)

        def entregar(tipo, identificador):
            movimento = mqtt_config.evento(tipo, "produtor", {"filaId": "fila-a"},
                                           event_id=identificador, timestamp=horario_antigo)
            mensagem = SimpleNamespace(
                topic=f"fila/fila-a/{tipo}",
                payload=json.dumps(movimento).encode(), mid=identificador, qos=1,
            )
            modulo["on_message"](cliente, None, mensagem)

        entregar("contagem", "chegada-1")
        self.assertFalse(any(p[0] == "fila/fila-a/estado"
                             for p in cliente.publicacoes))

        entregar("heartbeat", "batimento-1")
        estados = [p[1] for p in cliente.publicacoes
                   if p[0] == "fila/fila-a/estado"]
        # Publicado no contrato, correlacionado ao heartbeat que provocou o recálculo.
        self.assertEqual(mqtt_config.ler_evento("fila/fila-a/estado", json.dumps(estados[-1])), estados[-1])
        self.assertEqual((estados[-1]["payload"]["ocupacao"], estados[-1]["correlation_id"]), (1, "batimento-1"))
        self.assertTrue(modulo["heartbeat_recente"](
            "fila-a", time.monotonic()))

        entregar("saida", "saida-1")
        self.assertEqual(modulo["ocupacao_de"]("fila-a"), 0)

        motor = modulo["estado_persistente"].motor
        estado = modulo["estado_persistente"]
        cadastrar(motor,
                  Usuario(usuario_id="usuario-1", login="ana", senha_hash="x", nome="Ana", face_id="f1"),
                  Usuario(usuario_id="usuario-2", login="bia", senha_hash="x", nome="Bia", face_id="f2"),
                  Usuario(usuario_id="validador-1", login="vera", senha_hash="x", nome="Vera",
                          face_id="f3", papel="validador"))
        cadastrar(motor, Ingresso(ingresso_id="ING-1", usuario_id="usuario-1"),
                  Ingresso(ingresso_id="ING-2", usuario_id="usuario-2"))

        # O reconhecimento chega pronto do backend; o processador aplica as regras do ingresso.
        casos = (
            ("reconhecido", "usuario-1", "ING-1", "validador-1", "aceito", None),
            ("reconhecido", "usuario-1", "ING-1", "validador-1", "recusado", "ingresso-ja-usado"),
            ("reconhecido", "usuario-1", "ING-2", "validador-1", "recusado", "rosto-nao-confere"),
            ("nao-reconhecido", None, "ING-2", "validador-1", "recusado", "rosto-nao-confere"),
            ("reconhecido", "usuario-1", "NAO-EXISTE", "validador-1", "recusado", "ingresso-inexistente"),
            ("falha", None, "ING-2", "validador-1", "indeterminado", "falha-reconhecimento"),
            ("reconhecido", "usuario-2", "ING-2", "usuario-1", "recusado", "validador-nao-autorizado"),
        )
        for numero, (reconhecimento, usuario, ingresso, validador, esperado, motivo) in enumerate(casos):
            dados = {"filaId": "fila-a", "fotoRef": f"leituras/{numero}.jpg", "ingressoId": ingresso,
                     "validadorId": validador, "reconhecimento": reconhecimento}
            if usuario:
                dados["usuarioReconhecido"] = usuario
            leitura = mqtt_config.evento("leitura", "backend", dados, correlation_id=f"operacao-{numero}",
                                         event_id=f"leitura-{numero}", timestamp=horario_antigo)
            mensagem = SimpleNamespace(topic="fila/fila-a/leitura",
                                       payload=json.dumps(leitura).encode(),
                                       mid=leitura["event_id"], qos=1)
            modulo["on_message"](cliente, None, mensagem)
            self.assertIn(mensagem.mid, cliente.confirmadas)
            # O resultado sai da saída (outbox) e fica pendente até o PUBACK.
            primeira = len(cliente.publicacoes)
            pendente = [linha[0] for linha in estado.saida_pendente()]
            self.assertEqual(pendente, [f"leitura-{numero}-resultado"])
            modulo["on_publish"](cliente, None, primeira, 0, None)
            self.assertEqual(estado.saida_pendente(), [])
            # Reentrega: a decisão gravada sai de novo (mesmo evento), sem gastar ingresso,
            # e a duplicata vai para os rejeitados.
            modulo["on_message"](cliente, None, mensagem)
            (_, repetido, _), (topico_rejeicao, rejeicao, _) = cliente.publicacoes[-2:]
            self.assertEqual(repetido, cliente.publicacoes[primeira - 1][1])
            self.assertEqual((topico_rejeicao, rejeicao["payload"]["motivo"], rejeicao["correlation_id"]),
                             ("sistema/processador/rejeitado", "duplicado", f"operacao-{numero}"))
            modulo["on_publish"](cliente, None, len(cliente.publicacoes) - 1, 0, None)
            self.assertEqual(estado.saida_pendente(), [])
            topico, resultado, _ = cliente.publicacoes[primeira - 1]
            self.assertEqual(topico, "fila/fila-a/resultado")
            self.assertEqual(mqtt_config.ler_evento(topico, json.dumps(resultado)), resultado)
            self.assertEqual((resultado["event_id"], resultado["correlation_id"], resultado["source"]),
                             (f"leitura-{numero}-resultado", f"operacao-{numero}", "processador"))
            self.assertEqual((resultado["payload"]["leituraId"], resultado["payload"]["ingressoId"],
                              resultado["payload"]["resultado"], resultado["payload"].get("motivo")),
                             (leitura["event_id"], ingresso, esperado, motivo))
        self.assertEqual(modulo["ocupacao_de"]("fila-a"), 0)
        with modulo["estado_persistente"].sessao() as sessao:
            usado = sessao.get(Ingresso, "ING-1")
            self.assertEqual((usado.leitura_id, usado.fila_entrada, usado.validador_id),
                             ("leitura-0", "fila-a", "validador-1"))
            self.assertIsNone(sessao.get(Ingresso, "ING-2").usado_em)

        # Leitura incompleta (sem ingresso, ou reconhecida sem usuário): rejeitada, sem resposta
        # e sem o conteúdo, que tem a referência da foto.
        publicadas = len(cliente.publicacoes)
        for numero, dados in enumerate(({"fotoRef": "x", "reconhecimento": "falha"},
                                        {"fotoRef": "x", "ingressoId": "ING-2", "validadorId": "validador-1",
                                         "reconhecimento": "reconhecido"})):
            incompleta = mqtt_config.evento("leitura", "backend", {"filaId": "fila-a", **dados},
                                            event_id=f"velha-{numero}", timestamp=horario_antigo)
            modulo["on_message"](cliente, None, SimpleNamespace(
                topic="fila/fila-a/leitura", payload=json.dumps(incompleta).encode(),
                mid=f"velha-{numero}", qos=1))
            self.assertIn(f"velha-{numero}", cliente.confirmadas)
        self.assertEqual([(t, p["payload"]) for t, p, _ in cliente.publicacoes[publicadas:]],
                         [("sistema/processador/rejeitado", {"topico": "fila/fila-a/leitura",
                                                             "motivo": "leitura-incompleta",
                                                             "eventId": f"velha-{n}"}) for n in range(2)])

        modulo["on_message"](cliente, None, SimpleNamespace(
            topic="fila/fila-a/heartbeat", payload=b"teste-acl", mid=99, qos=1))
        self.assertIn(99, cliente.confirmadas)
        self.assertEqual(cliente.publicacoes[-1][1]["payload"],
                         {"topico": "fila/fila-a/heartbeat", "motivo": "fora-do-contrato", "conteudo": "teste-acl"})
        self.assertEqual(cliente.confirmadas[:3],
                         ["chegada-1", "batimento-1", "saida-1"])

        modulo["ultimo_heartbeat_recebido"]["fila-a"] = time.monotonic() - 16
        self.assertFalse(modulo["heartbeat_recente"](
            "fila-a", time.monotonic()))
        motor.dispose()


if __name__ == "__main__":
    unittest.main()
