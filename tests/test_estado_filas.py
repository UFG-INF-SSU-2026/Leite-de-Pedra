import unittest

from apoio_banco import conexao_teste
from estado_filas import EstadoFilas


class EstadoFilasTest(unittest.TestCase):
    def test_persiste_e_deduplica_movimentos(self):
        estado = EstadoFilas(conexao_teste())
        chegada = {"eventId": "sensor-1", "eventTimeMs": 1000}
        saida = {"eventId": "sensor-2", "eventTimeMs": 2000}

        self.assertEqual(estado.aplicar("fila-a", "contagem", chegada),
                         (True, 1, 0))
        self.assertEqual(estado.aplicar("fila-a", "contagem", chegada),
                         (False, 1, 0))
        self.assertEqual(estado.ocupacao("fila-a"), 1)

        estado.conexao.close()
        restaurado = EstadoFilas(conexao_teste(limpar=False))
        self.assertEqual(restaurado.ocupacao("fila-a"), 1)
        self.assertEqual(restaurado.aplicar("fila-a", "saida", saida),
                         (True, 1, 1))
        self.assertEqual(restaurado.aplicar("fila-a", "saida", saida),
                         (False, 1, 1))
        self.assertEqual(restaurado.ocupacao("fila-a"), 0)

        extra = {"eventId": "sensor-3", "eventTimeMs": 3000}
        self.assertEqual(restaurado.aplicar("fila-a", "saida", extra),
                         (True, 1, 1))

        restaurado.registrar_resultado({"eventId": "leitura-1", "filaId": "fila-a",
                                        "eventTimeMs": 4000, "resultado": "aceito"})
        restaurado.registrar_estado("fila-a", "livre", 0, 0)
        tipos = restaurado.conexao.execute(
            "SELECT tipo, count(*) FROM movimentos GROUP BY tipo ORDER BY tipo"
        ).fetchall()
        self.assertEqual(tipos, [("contagem", 1), ("resultado", 1), ("saida", 2)])
        restaurado.conexao.close()


if __name__ == "__main__":
    unittest.main()
