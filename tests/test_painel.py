import json
import time
import unittest
import uuid
from datetime import datetime, timedelta

import jwt

from apoio_banco import conexao_teste
from estado_filas import EstadoFilas, conectar_banco
from observador.painel import ao_vivo, historico, paginas, sessao, usuarios
from observador.painel.configuracao import DURACAO_SESSAO_SEGUNDOS, LIMITE_SEM_HEARTBEAT_SEGUNDOS
from observador.painel.servidor import formatar_evento


class PainelTest(unittest.TestCase):
    def test_token_e_senha(self):
        chave = "a" * 64
        token = sessao.emitir_token("ana", chave)
        self.assertEqual(sessao.usuario_do_token(token, chave), "ana")
        self.assertIsNone(sessao.usuario_do_token(token, "b" * 64))
        self.assertIsNone(sessao.usuario_do_token(token[:-2] + "xx", chave))
        expirado = sessao.emitir_token("ana", chave, agora=time.time() - 2 * DURACAO_SESSAO_SEGUNDOS)
        self.assertIsNone(sessao.usuario_do_token(expirado, chave))
        sem_assinatura = jwt.encode({"sub": "ana", "iat": 1, "exp": 2**40}, None, algorithm="none")
        self.assertIsNone(sessao.usuario_do_token(sem_assinatura, chave))

        hash_guardado = usuarios.gerar_hash_senha("senha-correta")
        self.assertTrue(usuarios.senha_confere("senha-correta", hash_guardado))
        self.assertFalse(usuarios.senha_confere("senha-errada", hash_guardado))
        self.assertFalse(usuarios.senha_confere("x", "lixo"))

    def test_recebe_do_broker(self):
        ao_vivo.filas_ao_vivo.clear()
        ao_vivo.mensagens_recentes.clear()
        agora = datetime.now().astimezone()
        agora_ms = int(agora.timestamp() * 1000)

        def receber(tipo, payload, fila="fila-a"):
            return ao_vivo.registrar_mensagem(f"fila/{fila}/{tipo}", json.dumps(payload).encode(), agora)

        self.assertFalse(ao_vivo.registrar_mensagem("fila/fila-a/heartbeat", b"teste-acl"))
        self.assertFalse(receber("contagem", {"filaId": "fila-b", "eventTimeMs": agora_ms}))
        self.assertFalse(receber("leitura", {"filaId": "fila-a", "fotoRef": "x.jpg"}))

        self.assertTrue(receber("heartbeat", {"filaId": "fila-a", "eventTimeMs": agora_ms}))
        receber("contagem", {"filaId": "fila-a", "eventId": "c1", "eventTimeMs": agora_ms - 40})
        receber("estado", {"filaId": "fila-a", "semaforo": "atencao", "ocupacao": 3,
                           "sentidoRecomendado": "fila-b", "tempoEsperaEstimado": 21})
        receber("recomendacao", {"filaId": "fila-a", "sentidoRecomendado": "fila-b",
                                 "motivo": "<script>alert(1)</script>"})
        receber("resultado", {"filaId": "fila-a", "eventId": "l1", "resultado": "aceito",
                              "eventTimeMs": agora_ms})

        situacao = ao_vivo.situacao_atual(agora)
        fila = situacao["filas"][0]
        self.assertTrue(fila["enlace_ativo"])
        self.assertEqual((fila["entradas"], fila["estado"]["ocupacao"],
                          fila["ultimo_resultado"]["resultado"]), (1, 3, "aceito"))
        self.assertEqual([m["tipo"] for m in situacao["mensagens"]],
                         ["resultado", "recomendacao", "estado", "contagem"])
        self.assertAlmostEqual(situacao["mensagens"][-1]["latencia_ms"], 40, delta=1)
        depois = ao_vivo.situacao_atual(agora + timedelta(seconds=LIMITE_SEM_HEARTBEAT_SEGUNDOS + 1))
        self.assertFalse(depois["filas"][0]["enlace_ativo"])

        html = paginas.renderizar_painel("ana", situacao, None)
        self.assertIn("&lt;script&gt;alert", html)
        self.assertNotIn("<script>alert", html)
        self.assertIn("Banco indisponível", html)

        evento = formatar_evento("ao-vivo", paginas.renderizar_ao_vivo(situacao)).decode()
        self.assertTrue(evento.startswith("event: ao-vivo\ndata: "))
        self.assertTrue(evento.endswith("\n\n"))
        self.assertNotIn("\n\n", evento[:-2])

    def test_historico_do_banco(self):
        estado = EstadoFilas(conexao_teste())
        agora = int(time.time() * 1000)
        fila = f"fila-{uuid.uuid4().hex[:8]}"
        estado.aplicar(fila, "contagem", {"eventId": "c1", "eventTimeMs": agora})
        estado.aplicar(fila, "contagem", {"eventId": "c2", "eventTimeMs": agora})
        estado.registrar_resultado({"eventId": "l1", "filaId": fila,
                                    "eventTimeMs": agora, "resultado": "aceito"})
        estado.registrar_estado(fila, "atencao", 1, 20)
        estado.conexao.close()

        with conectar_banco("observador", banco="filas_teste") as conexao:
            linhas = [m for m in historico.historico_por_minuto(conexao) if m["fila_id"] == fila]
        self.assertEqual((sum(m["entradas"] for m in linhas), sum(m["aceitos"] for m in linhas),
                          max(m["espera_maxima"] for m in linhas)), (2, 1, 20))


if __name__ == "__main__":
    unittest.main()
