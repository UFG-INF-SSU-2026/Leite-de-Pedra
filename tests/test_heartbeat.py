"""O relógio simulado não deve decidir se o enlace MQTT está ativo."""

import json
import runpy
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import banco
import estado_filas
import mqtt_config


class ClienteFalso:
    def __init__(self):
        self.publicacoes = []

    def publish(self, topico, payload, **opcoes):
        self.publicacoes.append((topico, json.loads(payload), opcoes))
        return SimpleNamespace(rc=0)


class HeartbeatTest(unittest.TestCase):
    def test_horario_antigo_do_esp_nao_bloqueia_estado(self):
        banco_original = banco.BancoEmMemoria
        estado_original = estado_filas.EstadoFilas
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "filas.sqlite3"
            with patch.object(banco, "BancoEmMemoria",
                              side_effect=lambda _: banco_original()), \
                 patch.object(estado_filas, "EstadoFilas",
                              side_effect=lambda: estado_original(arquivo)), \
                 patch.object(mqtt_config, "conectar"), \
                 patch("threading.Thread.start"), \
                 patch("paho.mqtt.client.Client.loop_forever"):
                modulo = runpy.run_path("processador/processador.py")

            cliente = ClienteFalso()
            horario_antigo = int((time.time() - 120) * 1000)

            def entregar(tipo, identificador):
                payload = {"eventId": identificador, "filaId": "fila-a",
                           "tipo": tipo, "eventTimeMs": horario_antigo}
                mensagem = SimpleNamespace(
                    topic=f"fila/fila-a/{tipo}",
                    payload=json.dumps(payload).encode(),
                )
                modulo["on_message"](cliente, None, mensagem)

            entregar("contagem", "chegada-1")
            self.assertFalse(any(p[0] == "fila/fila-a/estado"
                                 for p in cliente.publicacoes))

            entregar("heartbeat", "batimento-1")
            estados = [p[1] for p in cliente.publicacoes
                       if p[0] == "fila/fila-a/estado"]
            self.assertEqual(estados[-1]["ocupacao"], 1)
            self.assertTrue(modulo["heartbeat_recente"](
                "fila-a", time.monotonic()))

            modulo["ultimo_heartbeat_recebido"]["fila-a"] = time.monotonic() - 16
            self.assertFalse(modulo["heartbeat_recente"](
                "fila-a", time.monotonic()))
            modulo["estado_persistente"].conexao.close()


if __name__ == "__main__":
    unittest.main()
