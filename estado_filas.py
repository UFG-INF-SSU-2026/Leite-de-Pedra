"""Estado persistente e deduplicação dos eventos de movimento das filas."""

import os
import sqlite3
from pathlib import Path


CAMINHO_PADRAO = Path(os.getenv(
    "FILAS_DB", str(Path(__file__).resolve().parent / ".local" / "filas.sqlite3")
))


class EstadoFilas:
    def __init__(self, caminho=CAMINHO_PADRAO):
        caminho = Path(caminho)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self.conexao = sqlite3.connect(caminho)
        self.conexao.execute("PRAGMA busy_timeout=5000")
        self.conexao.execute("PRAGMA journal_mode=WAL")
        self.conexao.execute(
            "CREATE TABLE IF NOT EXISTS filas ("
            "fila_id TEXT PRIMARY KEY, entradas INTEGER NOT NULL DEFAULT 0, "
            "saidas INTEGER NOT NULL DEFAULT 0)"
        )
        self.conexao.execute(
            "CREATE TABLE IF NOT EXISTS movimentos ("
            "evento_id TEXT PRIMARY KEY, fila_id TEXT NOT NULL, tipo TEXT NOT NULL, "
            "recebido_em_ms INTEGER NOT NULL)"
        )
        self.conexao.commit()

    def listar(self):
        return list(self.conexao.execute(
            "SELECT fila_id, entradas, saidas FROM filas ORDER BY fila_id"
        ))

    def ocupacao(self, fila_id):
        linha = self.conexao.execute(
            "SELECT entradas - saidas FROM filas WHERE fila_id = ?", (fila_id,)
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
        with self.conexao:
            self.conexao.execute(
                "INSERT OR IGNORE INTO filas (fila_id) VALUES (?)", (fila_id,)
            )
            cursor = self.conexao.execute(
                "INSERT OR IGNORE INTO movimentos "
                "(evento_id, fila_id, tipo, recebido_em_ms) VALUES (?, ?, ?, ?)",
                (identificador, fila_id, tipo, int(payload["eventTimeMs"])),
            )
            novo = cursor.rowcount == 1
            if novo and tipo == "contagem":
                self.conexao.execute(
                    "UPDATE filas SET entradas = entradas + 1 WHERE fila_id = ?",
                    (fila_id,),
                )
            elif novo and tipo == "saida":
                self.conexao.execute(
                    "UPDATE filas SET saidas = saidas + 1 "
                    "WHERE fila_id = ? AND saidas < entradas", (fila_id,)
                )
            entradas, saidas = self.conexao.execute(
                "SELECT entradas, saidas FROM filas WHERE fila_id = ?", (fila_id,)
            ).fetchone()
        return novo, entradas, saidas
