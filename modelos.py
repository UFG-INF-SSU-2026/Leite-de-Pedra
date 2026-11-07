"""Modelos SQLAlchemy das tabelas do TimescaleDB e conexão por papel.

As tabelas, hypertables, agregados contínuos e permissões são criados por
banco/esquema.sql e banco/ingressos.sql (recursos do TimescaleDB e GRANTs por
coluna que o ORM não expressa); estes modelos só os mapeiam.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (BigInteger, Column, DateTime, ForeignKey, Identity, Integer, MetaData, Table,
                        Text, URL, create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

RAIZ_PROJETO = Path(__file__).resolve().parent
PASTA_SEGREDOS = RAIZ_PROJETO / ".local" / "banco"


def criar_motor(papel="processador", banco=None):
    """Engine com TLS verify-full e a senha do papel em .local/banco/<papel>.password."""
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
    url = URL.create(
        "postgresql+psycopg",
        username=papel,
        password=senha,
        host=os.getenv("FILAS_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("FILAS_DB_PORT", "5433")),
        database=banco or os.getenv("FILAS_DB", "filas"),
        query={
            "sslmode": "verify-full",
            "sslrootcert": os.getenv("FILAS_DB_CA", str(RAIZ_PROJETO / ".local" / "mqtt" / "ca.crt")),
        },
    )
    return create_engine(url, pool_pre_ping=True)


def fabrica_de_sessoes(motor):
    # Os objetos continuam legíveis depois do commit, fora da sessão.
    return sessionmaker(motor, expire_on_commit=False)


def de_milissegundos(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def em_milissegundos(momento):
    return round(momento.timestamp() * 1000)


class Base(DeclarativeBase):
    pass


class Fila(Base):
    __tablename__ = "filas"
    fila_id: Mapped[str] = mapped_column(Text, primary_key=True)
    entradas: Mapped[int] = mapped_column(Integer, server_default="0")
    saidas: Mapped[int] = mapped_column(Integer, server_default="0")


class Movimento(Base):
    __tablename__ = "movimentos"
    evento_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tipo: Mapped[str] = mapped_column(Text, primary_key=True)
    momento: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    fila_id: Mapped[str] = mapped_column(Text)
    recebido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    resultado: Mapped[str | None] = mapped_column(Text)
    motivo: Mapped[str | None] = mapped_column(Text)
    ingresso_id: Mapped[str | None] = mapped_column(Text)
    validador_id: Mapped[str | None] = mapped_column(Text)
    # Do contrato das mensagens: a operação de ponta a ponta e quem publicou.
    correlacao_id: Mapped[str | None] = mapped_column(Text)
    origem: Mapped[str | None] = mapped_column(Text)


class Estado(Base):
    __tablename__ = "estados"
    momento: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    fila_id: Mapped[str] = mapped_column(Text)
    semaforo: Mapped[str] = mapped_column(Text)
    ocupacao: Mapped[int] = mapped_column(Integer)
    espera_segundos: Mapped[int | None] = mapped_column(Integer)
    # A hypertable não tem chave primária; o ORM precisa de uma para mapear.
    __mapper_args__ = {"primary_key": [momento, fila_id]}


class Usuario(Base):
    __tablename__ = "usuarios"
    usuario_id: Mapped[str] = mapped_column(Text, primary_key=True)
    login: Mapped[str] = mapped_column(Text, unique=True)
    senha_hash: Mapped[str] = mapped_column(Text)
    nome: Mapped[str] = mapped_column(Text)
    papel: Mapped[str] = mapped_column(Text, server_default="cliente")
    face_id: Mapped[str] = mapped_column(Text, unique=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    # Sem RETURNING dos valores padrão: o processador só pode ler usuario_id e papel.
    __mapper_args__ = {"eager_defaults": False}


class Ingresso(Base):
    __tablename__ = "ingressos"
    ingresso_id: Mapped[str] = mapped_column(Text, primary_key=True)
    usuario_id: Mapped[str] = mapped_column(ForeignKey("usuarios.usuario_id"))
    emitido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    usado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fila_entrada: Mapped[str | None] = mapped_column(Text)
    leitura_id: Mapped[str | None] = mapped_column(Text, unique=True)
    validador_id: Mapped[str | None] = mapped_column(ForeignKey("usuarios.usuario_id"))
    cancelado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __mapper_args__ = {"eager_defaults": False}


class Saida(Base):
    """Transactional outbox: gravada com a decisão, publicada depois pelo processador."""
    __tablename__ = "saida"
    evento_id: Mapped[str] = mapped_column(Text, primary_key=True)
    topico: Mapped[str] = mapped_column(Text)
    conteudo: Mapped[str] = mapped_column(Text)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    publicado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __mapper_args__ = {"eager_defaults": False}


class Auditoria(Base):
    __tablename__ = "auditoria"
    auditoria_id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    momento: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="now()")
    admin_id: Mapped[str] = mapped_column(ForeignKey("usuarios.usuario_id"))
    acao: Mapped[str] = mapped_column(Text)
    alvo: Mapped[str] = mapped_column(Text)
    detalhe: Mapped[str | None] = mapped_column(Text)


# Agregados contínuos (somente leitura, usados pelo dashboard de admin).
_visoes = MetaData()
movimentos_por_minuto = Table(
    "movimentos_por_minuto", _visoes,
    Column("minuto", DateTime(timezone=True)), Column("fila_id", Text),
    Column("entradas", Integer), Column("saidas", Integer), Column("aceitos", Integer),
    Column("recusados", Integer), Column("indeterminados", Integer),
)
espera_por_minuto = Table(
    "espera_por_minuto", _visoes,
    Column("minuto", DateTime(timezone=True)), Column("fila_id", Text),
    Column("espera_media", Integer), Column("espera_maxima", Integer),
    Column("ocupacao_maxima", Integer),
)
