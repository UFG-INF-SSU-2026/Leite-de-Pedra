"""Histórico operacional do que o processador gravou, para o dashboard.

Usa o papel observador do banco, que só lê filas, movimentos, estados, os
agregados e a saída (outbox): nada de usuários, ingressos ou auditoria, que são
da gestão no backend. Sem autenticação aqui: o backend confere o admin e repassa.
"""

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Query
from sqlalchemy import and_, func, select

from modelos import (Estado, Fila, Movimento, Saida, criar_motor, espera_por_minuto,
                     fabrica_de_sessoes, movimentos_por_minuto)

sessao = fabrica_de_sessoes(criar_motor("observador"))
rotas = APIRouter()

Limite = Query(100, ge=1, le=500)
Deslocamento = Query(0, ge=0)


def pagina(s, consulta, limite, deslocamento, converter):
    total = s.scalar(select(func.count()).select_from(consulta.order_by(None).subquery()))
    linhas = s.execute(consulta.limit(limite).offset(deslocamento)).all()
    return {"total": total, "itens": [converter(linha) for linha in linhas]}


def movimento_json(m):
    return {"eventId": m.evento_id, "tipo": m.tipo, "filaId": m.fila_id, "momento": m.momento,
            "recebidoEm": m.recebido_em, "resultado": m.resultado, "motivo": m.motivo,
            "ingressoId": m.ingresso_id, "validadorId": m.validador_id,
            "correlationId": m.correlacao_id, "origem": m.origem}


@rotas.get("/resumo")
def resumo():
    """Filas, decisões das leituras e o que ainda falta o broker confirmar."""
    with sessao() as s:
        resultados = dict(s.execute(
            select(Movimento.resultado, func.count())
            .where(Movimento.tipo == "resultado").group_by(Movimento.resultado)).all())
        filas = s.scalars(select(Fila).order_by(Fila.fila_id)).all()
        # Resultados decididos que o broker ainda não confirmou (outbox).
        pendentes = s.scalar(select(func.count()).select_from(Saida).where(Saida.publicado_em.is_(None)))
    return {
        "saidaPendente": pendentes,
        "leituras": {r: resultados.get(r, 0) for r in ("aceito", "recusado", "indeterminado")},
        "filas": [{"filaId": f.fila_id, "entradas": f.entradas, "saidas": f.saidas,
                   "ocupacao": f.entradas - f.saidas} for f in filas],
    }


@rotas.get("/historico")
def historico(minutos: int = Query(60, ge=1, le=1440)):
    desde = datetime.now(timezone.utc) - timedelta(minutes=minutos)
    m = select(movimentos_por_minuto).where(movimentos_por_minuto.c.minuto > desde).subquery()
    e = select(espera_por_minuto).where(espera_por_minuto.c.minuto > desde).subquery()
    minuto = func.coalesce(m.c.minuto, e.c.minuto).label("minuto")
    fila_id = func.coalesce(m.c.fila_id, e.c.fila_id).label("filaId")
    contagens = ("entradas", "saidas", "aceitos", "recusados", "indeterminados")
    consulta = (
        select(minuto, fila_id, *(func.coalesce(m.c[nome], 0).label(nome) for nome in contagens),
               e.c.espera_media.label("esperaMedia"), e.c.espera_maxima.label("esperaMaxima"),
               e.c.ocupacao_maxima.label("ocupacaoMaxima"))
        .select_from(m.join(e, and_(m.c.minuto == e.c.minuto, m.c.fila_id == e.c.fila_id),
                            full=True))
        .order_by(minuto.desc(), fila_id)
    )
    with sessao() as s:
        return [dict(linha._mapping) for linha in s.execute(consulta)]


@rotas.get("/leituras")
def leituras(resultado: Literal["aceito", "recusado", "indeterminado"] | None = None,
             fila: str | None = Query(None, max_length=40),
             ingresso: str | None = Query(None, max_length=64),
             limite: int = Limite, deslocamento: int = Deslocamento):
    """Cada decisão do processador: ingresso, validador, resultado e motivo."""
    consulta = select(Movimento).where(Movimento.tipo == "resultado").order_by(Movimento.momento.desc())
    if resultado:
        consulta = consulta.where(Movimento.resultado == resultado)
    if fila:
        consulta = consulta.where(Movimento.fila_id == fila)
    if ingresso:
        consulta = consulta.where(Movimento.ingresso_id == ingresso)
    with sessao() as s:
        return pagina(s, consulta, limite, deslocamento, lambda r: movimento_json(r[0]))


@rotas.get("/movimentos")
def movimentos(tipo: Literal["contagem", "saida", "leitura", "resultado"] | None = None,
               fila: str | None = Query(None, max_length=40),
               correlacao: str | None = Query(None, max_length=128),
               limite: int = Limite, deslocamento: int = Deslocamento):
    consulta = select(Movimento).order_by(Movimento.momento.desc())
    if correlacao:
        # O ciclo de uma operação: a leitura e o resultado dela, por exemplo.
        consulta = consulta.where(Movimento.correlacao_id == correlacao)
    if tipo:
        consulta = consulta.where(Movimento.tipo == tipo)
    if fila:
        consulta = consulta.where(Movimento.fila_id == fila)
    with sessao() as s:
        return pagina(s, consulta, limite, deslocamento, lambda r: movimento_json(r[0]))


@rotas.get("/estados")
def estados(fila: str | None = Query(None, max_length=40),
            limite: int = Limite, deslocamento: int = Deslocamento):
    consulta = select(Estado).order_by(Estado.momento.desc())
    if fila:
        consulta = consulta.where(Estado.fila_id == fila)
    with sessao() as s:
        return pagina(s, consulta, limite, deslocamento, lambda r: {
            "momento": r[0].momento, "filaId": r[0].fila_id, "semaforo": r[0].semaforo,
            "ocupacao": r[0].ocupacao, "esperaSegundos": r[0].espera_segundos})
