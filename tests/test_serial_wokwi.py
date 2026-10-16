"""A serial do Wokwi chega via RFC 2217; o painel deve mostrar só o texto."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "validacao"))
from servidor import sem_telnet


class SemTelnetTest(unittest.TestCase):
    def test_remove_negociacao_e_subnegociacao(self):
        dados = (b"\xff\xfb\x01WiFi\xff\xfa\x2c\x01\x00\x01\xc2\x00\xff\xf0"
                 b" conectado\r\n\xff\xff")
        self.assertEqual(sem_telnet(dados), b"WiFi conectado\r\n\xff")

    def test_texto_puro_passa_intacto(self):
        self.assertEqual(sem_telnet(b"MQTT/TLS autenticado\n"), b"MQTT/TLS autenticado\n")


if __name__ == "__main__":
    unittest.main()
