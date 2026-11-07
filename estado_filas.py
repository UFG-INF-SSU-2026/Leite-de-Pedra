from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from modelos import (Estado, Fila, Ingresso, Movimento, Saida, Usuario, criar_motor,
                     de_milissegundos, em_milissegundos, fabrica_de_sessoes)


class EstadoFilas:
    """Saldo das filas, movimentos e decisões das leituras, persistidos pelo processador."""

    def __init__(self, motor=None):
        self.motor = motor or criar_motor()
        self.sessao = fabrica_de_sessoes(self.motor)

    def listar(self):
        with self.sessao() as s:
            filas = s.scalars(select(Fila).order_by(Fila.fila_id))
            return [(f.fila_id, f.entradas, f.saidas) for f in filas]

    def ocupacao(self, fila_id):
        with self.sessao() as s:
            fila = s.get(Fila, fila_id)
        return fila.entradas - fila.saidas if fila else 0

    def aplicar(self, fila_id, evento):
        """Grava um evento do contrato (mqtt_config) e devolve (novo, entradas, saidas).

        Duplicatas não alteram o saldo.
        """
        tipo = evento["event_type"]
        with self.sessao.begin() as s:
            s.execute(insert(Fila).values(fila_id=fila_id).on_conflict_do_nothing())
            fila = s.get(Fila, fila_id, with_for_update=True)
            # A chave (evento_id, tipo, momento) descarta as reentregas do QoS 1.
            novo = s.scalar(
                insert(Movimento).values(
                    evento_id=evento["event_id"], fila_id=fila_id, tipo=tipo,
                    momento=de_milissegundos(evento["timestamp"]),
                    correlacao_id=evento["correlation_id"], origem=evento["source"],
                ).on_conflict_do_nothing().returning(Movimento.evento_id)
            ) is not None
            if novo and tipo == "contagem":
                fila.entradas += 1
            elif novo and tipo == "saida" and fila.saidas < fila.entradas:
                fila.saidas += 1
        return novo, fila.entradas, fila.saidas

    def e_validador(self, usuario_id):
        with self.sessao() as s:
            return s.scalar(
                select(Usuario.usuario_id).where(Usuario.usuario_id == usuario_id,
                                                 Usuario.papel == "validador")
            ) is not None

    @staticmethod
    def _resultado_gravado(s, evento_id):
        linha = s.execute(
            select(Movimento.resultado, Movimento.motivo, Movimento.momento)
            .where(Movimento.evento_id == evento_id, Movimento.tipo == "resultado")
        ).first()
        return (linha.resultado, linha.motivo, em_milissegundos(linha.momento)) if linha else None

    def registrar_resultado(self, evento_id, fila_id, momento_ms, ingresso_id, resultado,
                            motivo=None, usuario_id=None, validador_id=None, correlacao_id=None,
                            mensagem=None):
        """Grava a decisão da leitura e devolve (resultado, motivo, eventTimeMs, nova).

        "aceito" chega aqui quando o rosto foi reconhecido como usuario_id; só
        se confirma se o ingresso apresentado for desse usuário e ainda não tiver
        sido usado. A marcação do ingresso, o resultado e a publicação dele na
        saída (outbox) ficam na mesma transação: uma queda no meio não gasta o
        ingresso sem resposta. Se a leitura já foi decidida, devolve a decisão
        gravada e põe a publicação dela na saída de novo.

        mensagem(resultado, motivo, eventTimeMs) -> (event_id, tópico, conteúdo).
        """
        with self.sessao.begin() as s:
            anterior = self._resultado_gravado(s, evento_id)
            if anterior:
                self._na_saida(s, mensagem, *anterior)
                return (*anterior, False)
            if resultado == "aceito":
                # Trava a linha: duas catracas com o mesmo ingresso não entram as duas.
                ingresso = s.get(Ingresso, ingresso_id, with_for_update=True)
                if ingresso is None:
                    resultado, motivo = "recusado", "ingresso-inexistente"
                elif ingresso.usuario_id != usuario_id:
                    resultado, motivo = "recusado", "rosto-nao-confere"
                elif ingresso.cancelado_em is not None:
                    resultado, motivo = "recusado", "ingresso-cancelado"
                elif ingresso.usado_em is not None:
                    resultado, motivo = "recusado", "ingresso-ja-usado"
                else:
                    ingresso.usado_em = de_milissegundos(momento_ms)
                    ingresso.fila_entrada = fila_id
                    ingresso.leitura_id = evento_id
                    ingresso.validador_id = validador_id
            s.add(Movimento(evento_id=evento_id, fila_id=fila_id, tipo="resultado",
                            momento=de_milissegundos(momento_ms), resultado=resultado,
                            motivo=motivo, ingresso_id=ingresso_id, validador_id=validador_id,
                            correlacao_id=correlacao_id or evento_id, origem="processador"))
            self._na_saida(s, mensagem, resultado, motivo, momento_ms)
        return resultado, motivo, momento_ms, True

    @staticmethod
    def _na_saida(s, mensagem, *decisao):
        if mensagem is None:
            return
        evento_id, topico, conteudo = mensagem(*decisao)
        s.execute(insert(Saida).values(evento_id=evento_id, topico=topico, conteudo=conteudo)
                  .on_conflict_do_update(index_elements=[Saida.evento_id], set_={"publicado_em": None}))

    def saida_pendente(self, limite=100):
        """(event_id, tópico, conteúdo) que o broker ainda não confirmou, dos mais antigos."""
        with self.sessao() as s:
            return s.execute(select(Saida.evento_id, Saida.topico, Saida.conteudo)
                             .where(Saida.publicado_em.is_(None))
                             .order_by(Saida.criado_em).limit(limite)).all()

    def marcar_publicado(self, evento_id):
        with self.sessao.begin() as s:
            s.execute(update(Saida).where(Saida.evento_id == evento_id).values(publicado_em=func.now()))

    def registrar_estado(self, fila_id, semaforo, ocupacao, espera):
        with self.sessao.begin() as s:
            s.add(Estado(momento=datetime.now(timezone.utc), fila_id=fila_id, semaforo=semaforo, ocupacao=ocupacao,
                         espera_segundos=espera))
