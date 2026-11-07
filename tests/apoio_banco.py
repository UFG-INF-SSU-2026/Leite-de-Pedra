import unittest

from sqlalchemy import delete

from modelos import (PASTA_SEGREDOS, Auditoria, Estado, Fila, Ingresso, Movimento, Saida, Usuario,
                     criar_motor, fabrica_de_sessoes)


def motor_teste(limpar=True):
    if not (PASTA_SEGREDOS / "processador.password").exists():
        raise unittest.SkipTest(
            "Banco não configurado: execute banco/configurar-banco.sh e banco/iniciar-banco.sh"
        )
    motor = criar_motor("processador", banco="filas_teste")
    if limpar:
        with fabrica_de_sessoes(motor).begin() as s:
            for modelo in (Auditoria, Ingresso, Usuario, Movimento, Estado, Fila, Saida):  # ordem das chaves estrangeiras
                s.execute(delete(modelo))
    return motor


def cadastrar(motor, *objetos):
    with fabrica_de_sessoes(motor).begin() as s:
        s.add_all(objetos)
