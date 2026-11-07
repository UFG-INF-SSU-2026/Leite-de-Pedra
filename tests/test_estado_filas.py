import unittest

from sqlalchemy import func, select

from apoio_banco import motor_teste
from estado_filas import EstadoFilas
from modelos import Movimento
from mqtt_config import evento


class EstadoFilasTest(unittest.TestCase):
    def test_persiste_e_deduplica_movimentos(self):
        estado = EstadoFilas(motor_teste())
        def movimento(tipo, identificador, momento):
            return evento(tipo, "produtor", {"filaId": "fila-a"}, event_id=identificador, timestamp=momento)

        chegada = movimento("contagem", "sensor-1", 1000)
        saida = movimento("saida", "sensor-2", 2000)

        self.assertEqual(estado.aplicar("fila-a", chegada),
                         (True, 1, 0))
        self.assertEqual(estado.aplicar("fila-a", chegada),
                         (False, 1, 0))
        self.assertEqual(estado.ocupacao("fila-a"), 1)

        estado.motor.dispose()
        restaurado = EstadoFilas(motor_teste(limpar=False))
        self.assertEqual(restaurado.ocupacao("fila-a"), 1)
        self.assertEqual(restaurado.aplicar("fila-a", saida),
                         (True, 1, 1))
        self.assertEqual(restaurado.aplicar("fila-a", saida),
                         (False, 1, 1))
        self.assertEqual(restaurado.ocupacao("fila-a"), 0)

        extra = movimento("saida", "sensor-3", 3000)
        self.assertEqual(restaurado.aplicar("fila-a", extra),
                         (True, 1, 1))

        restaurado.registrar_resultado("leitura-1", "fila-a", 4000, "ING-X", "recusado",
                                       "rosto-nao-confere")
        restaurado.registrar_estado("fila-a", "livre", 0, 0)
        with restaurado.sessao() as sessao:
            tipos = sessao.execute(select(Movimento.tipo, func.count()).group_by(Movimento.tipo)
                                   .order_by(Movimento.tipo)).all()
        self.assertEqual([tuple(t) for t in tipos], [("contagem", 1), ("resultado", 1), ("saida", 2)])
        with restaurado.sessao() as sessao:
            gravado = sessao.execute(select(Movimento.correlacao_id, Movimento.origem)
                                     .where(Movimento.evento_id == "sensor-1")).one()
        self.assertEqual(tuple(gravado), ("sensor-1", "produtor"))
        restaurado.motor.dispose()


if __name__ == "__main__":
    unittest.main()
