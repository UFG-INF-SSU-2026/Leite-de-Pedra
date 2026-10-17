from estado_filas import conectar_banco

from .configuracao import MINUTOS_DE_HISTORICO

CONSULTA_POR_MINUTO = """
    SELECT coalesce(m.minuto, e.minuto) AS minuto,
           coalesce(m.fila_id, e.fila_id) AS fila_id,
           coalesce(m.entradas, 0) AS entradas, coalesce(m.saidas, 0) AS saidas,
           coalesce(m.aceitos, 0) AS aceitos, coalesce(m.recusados, 0) AS recusados,
           coalesce(m.indeterminados, 0) AS indeterminados,
           e.espera_media, e.espera_maxima, e.ocupacao_maxima
    FROM (SELECT * FROM movimentos_por_minuto
          WHERE minuto > now() - make_interval(mins => %(minutos)s)) m
    FULL JOIN (SELECT * FROM espera_por_minuto
               WHERE minuto > now() - make_interval(mins => %(minutos)s)) e
      ON m.minuto = e.minuto AND m.fila_id = e.fila_id
    ORDER BY minuto DESC, fila_id
"""


def historico_por_minuto(conexao):
    cursor = conexao.execute(CONSULTA_POR_MINUTO, {"minutos": MINUTOS_DE_HISTORICO})
    colunas = [coluna.name for coluna in cursor.description]
    return [dict(zip(colunas, linha)) for linha in cursor.fetchall()]


def consultar_historico():
    try:
        with conectar_banco("observador") as conexao:
            return historico_por_minuto(conexao)
    except Exception as erro:
        print(f"Falha ao consultar o banco: {erro}")
        return None
