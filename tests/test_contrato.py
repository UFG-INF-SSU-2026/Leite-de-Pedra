"""Contrato das mensagens MQTT: o que ler_evento aceita e o que descarta."""

import json
import unittest

from mqtt_config import evento, ler_evento


class ContratoTest(unittest.TestCase):
    def test_aceita_so_mensagem_do_contrato_que_combina_com_o_topico(self):
        chegada = evento("contagem", "produtor", {"filaId": "fila-a"})
        self.assertEqual(chegada["correlation_id"], chegada["event_id"])  # abre uma operação
        self.assertEqual(ler_evento("fila/fila-a/contagem", json.dumps(chegada)), chegada)

        recusadas = {
            "fila/fila-b/contagem": chegada,                            # filaId de outra fila
            "fila/fila-a/saida": chegada,                               # event_type diferente do tópico
            "outro/fila-a/contagem": chegada,                           # raiz desconhecida
            "sistema/backend/status": evento("status", "produtor", {}),  # status em nome de outro
        }
        for topico, mensagem in recusadas.items():
            self.assertIsNone(ler_evento(topico, json.dumps(mensagem)), topico)
        for campo, valor in (("event_id", ""), ("correlation_id", None), ("timestamp", True),
                             ("timestamp", "1700000000000"), ("payload", []), ("source", "x" * 129)):
            self.assertIsNone(ler_evento("fila/fila-a/contagem", json.dumps({**chegada, campo: valor})),
                              campo)
        self.assertIsNone(ler_evento("fila/fila-a/contagem", b"\xff nao e json"))

        status = evento("status", "backend", {"online": True})
        self.assertEqual(ler_evento("sistema/backend/status", json.dumps(status)), status)


if __name__ == "__main__":
    unittest.main()
