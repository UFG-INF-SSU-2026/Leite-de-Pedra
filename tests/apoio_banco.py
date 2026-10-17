import unittest

from estado_filas import PASTA_SEGREDOS, conectar_banco


def conexao_teste(limpar=True):
    if not (PASTA_SEGREDOS / "processador.password").exists():
        raise unittest.SkipTest(
            "Banco não configurado: execute banco/configurar-banco.sh e banco/iniciar-banco.sh"
        )
    conexao = conectar_banco("processador", banco="filas_teste")
    if limpar:
        conexao.execute("TRUNCATE filas, movimentos, estados")
    return conexao
