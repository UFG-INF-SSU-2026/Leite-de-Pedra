import os
import threading
from pathlib import Path

import psycopg


RAIZ_PROJETO = Path(__file__).resolve().parent
PASTA_SEGREDOS = RAIZ_PROJETO / ".local" / "banco"


def conectar_banco(papel="processador", banco=None):
    senha = os.getenv("FILAS_DB_PASSWORD")
    if not senha:
        arquivo = PASTA_SEGREDOS / f"{papel}.password"
        try:
            senha = arquivo.read_text(encoding="utf-8").strip()
        except FileNotFoundError as erro:
            raise RuntimeError(
                f"Credencial do banco não encontrada em {arquivo}. "
                "Execute banco/configurar-banco.sh primeiro."
            ) from erro
    return psycopg.connect(
        host=os.getenv("FILAS_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("FILAS_DB_PORT", "5433")),
        dbname=banco or os.getenv("FILAS_DB", "filas"),
        user=papel,
        password=senha,
        sslmode="verify-full",
        sslrootcert=os.getenv(
            "FILAS_DB_CA", str(RAIZ_PROJETO / ".local" / "mqtt" / "ca.crt")
        ),
        autocommit=True,
    )


class EstadoFilas:
    def __init__(self, conexao=None):
        self.conexao = conexao or conectar_banco()
        self.trava = threading.Lock()

    def listar(self):
        with self.trava:
            return self.conexao.execute(
                "SELECT fila_id, entradas, saidas FROM filas ORDER BY fila_id"
            ).fetchall()

    def ocupacao(self, fila_id):
        with self.trava:
            linha = self.conexao.execute(
                "SELECT entradas - saidas FROM filas WHERE fila_id = %s", (fila_id,)
            ).fetchone()
        return linha[0] if linha else 0

    def aplicar(self, fila_id, tipo, payload):
        """Devolve (novo, entradas, saidas); duplicatas não alteram o saldo."""
        identificador = payload.get("eventId")
        if not identificador:
            identificador = (
                f"{fila_id}:{tipo}:{payload.get('sequence')}:"
                f"{payload.get('eventTimeMs')}"
            )
        with self.trava, self.conexao.transaction():
            self.conexao.execute(
                "INSERT INTO filas (fila_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (fila_id,),
            )
            novo = self.conexao.execute(
                "INSERT INTO movimentos (evento_id, fila_id, tipo, momento) "
                "VALUES (%s, %s, %s, to_timestamp(%s / 1000.0)) ON CONFLICT DO NOTHING",
                (identificador, fila_id, tipo, int(payload["eventTimeMs"])),
            ).rowcount == 1
            if novo and tipo == "contagem":
                self.conexao.execute(
                    "UPDATE filas SET entradas = entradas + 1 WHERE fila_id = %s",
                    (fila_id,),
                )
            elif novo and tipo == "saida":
                self.conexao.execute(
                    "UPDATE filas SET saidas = saidas + 1 "
                    "WHERE fila_id = %s AND saidas < entradas", (fila_id,)
                )
            entradas, saidas = self.conexao.execute(
                "SELECT entradas, saidas FROM filas WHERE fila_id = %s", (fila_id,)
            ).fetchone()
        return novo, entradas, saidas

    def tem_resultado(self, evento_id):
        with self.trava:
            return self.conexao.execute(
                "SELECT 1 FROM movimentos WHERE evento_id = %s AND tipo = 'resultado'",
                (evento_id,),
            ).fetchone() is not None

    def registrar_resultado(self, payload):
        with self.trava:
            self.conexao.execute(
                "INSERT INTO movimentos (evento_id, fila_id, tipo, momento, resultado) "
                "VALUES (%s, %s, 'resultado', to_timestamp(%s / 1000.0), %s) "
                "ON CONFLICT DO NOTHING",
                (payload["eventId"], payload["filaId"], payload["eventTimeMs"],
                 payload["resultado"]),
            )

    def registrar_estado(self, fila_id, semaforo, ocupacao, espera):
        with self.trava:
            self.conexao.execute(
                "INSERT INTO estados (fila_id, semaforo, ocupacao, espera_segundos) "
                "VALUES (%s, %s, %s, %s)",
                (fila_id, semaforo, ocupacao, espera),
            )
