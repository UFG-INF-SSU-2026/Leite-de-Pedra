import tempfile
import unittest
from pathlib import Path

from estado_filas import EstadoFilas


class EstadoFilasTest(unittest.TestCase):
    def test_persiste_e_deduplica_movimentos(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "filas.sqlite3"
            estado = EstadoFilas(arquivo)
            chegada = {"eventId": "sensor-1", "eventTimeMs": 1000}
            saida = {"eventId": "sensor-2", "eventTimeMs": 2000}

            self.assertEqual(estado.aplicar("fila-a", "contagem", chegada),
                             (True, 1, 0))
            self.assertEqual(estado.aplicar("fila-a", "contagem", chegada),
                             (False, 1, 0))
            self.assertEqual(estado.ocupacao("fila-a"), 1)

            estado.conexao.close()
            restaurado = EstadoFilas(arquivo)
            self.assertEqual(restaurado.ocupacao("fila-a"), 1)
            self.assertEqual(restaurado.aplicar("fila-a", "saida", saida),
                             (True, 1, 1))
            self.assertEqual(restaurado.aplicar("fila-a", "saida", saida),
                             (False, 1, 1))
            self.assertEqual(restaurado.ocupacao("fila-a"), 0)
            restaurado.conexao.close()


if __name__ == "__main__":
    unittest.main()
