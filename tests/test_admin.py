"""Dashboard de admin: acesso só para admins, todos os dados, gestão e auditoria."""

import json
import time
import unittest
from datetime import timedelta

from fastapi.testclient import TestClient

from apoio_backend import carregar_backend, s3, servir_observabilidade
from apoio_banco import cadastrar, motor_teste
from observabilidade import ao_vivo
from estado_filas import EstadoFilas
from modelos import Ingresso, Usuario
from mqtt_config import evento
from senhas import gerar_hash_senha


def usuario(usuario_id, papel="cliente"):
    return Usuario(usuario_id=usuario_id, login=usuario_id, nome=usuario_id.title(), papel=papel,
                   senha_hash=gerar_hash_senha(f"senha-de-{usuario_id}"), face_id=f"face-{usuario_id}")


class AdminTest(unittest.TestCase):
    def test_dashboard(self):
        motor = motor_teste()
        app_modulo = carregar_backend()
        s3.limpar()
        cadastrar(motor, usuario("ana"), usuario("vera", "validador"), usuario("adm", "admin"),
                  usuario("adm2", "admin"))
        cadastrar(motor, Ingresso(ingresso_id="AAAA00000001", usuario_id="ana"),
                  Ingresso(ingresso_id="AAAA00000002", usuario_id="ana"))
        estado = EstadoFilas(motor)
        estado.aplicar("fila-a", evento("contagem", "produtor", {"filaId": "fila-a"}, event_id="c1"))
        agora = int(time.time() * 1000)
        estado.registrar_resultado("l1", "fila-a", agora, "AAAA00000001", "aceito",
                                   usuario_id="ana", validador_id="vera")
        s3.chaves.append("leituras/l1.jpg")
        estado.registrar_resultado("l2", "fila-a", agora + 1, "AAAA00000001", "recusado",
                                   "rosto-nao-confere", validador_id="vera")
        estado.registrar_estado("fila-a", "atencao", 3, 20)

        with TestClient(app_modulo.app) as api:
            # Ao vivo e histórico vêm da observabilidade (um processo à parte), pela permissão do backend.
            app_modulo.admin.servicos.URL_OBSERVABILIDADE = "http://127.0.0.1:9"  # fora do ar
            self.assertEqual(api.get("/admin/historico", headers={"Authorization": "x"}).status_code, 401)
            observabilidade, url = servir_observabilidade()
            self.addCleanup(setattr, observabilidade, "should_exit", True)

            def entrar(login):
                token = api.post("/sessoes", json={"login": login, "senha": f"senha-de-{login}"}).json()
                return {"Authorization": f"Bearer {token['token']}"}

            adm, adm2, ana = entrar("adm"), entrar("adm2"), entrar("ana")
            self.assertEqual(api.get("/admin/resumo", headers=adm).status_code, 503)
            app_modulo.admin.servicos.URL_OBSERVABILIDADE = url
            self.assertEqual(api.get("/admin/resumo").status_code, 401)
            self.assertEqual(api.get("/admin/resumo", headers=ana).status_code, 403)

            resumo = api.get("/admin/resumo", headers=adm).json()
            self.assertEqual(resumo["saidaPendente"], 0)
            self.assertEqual(resumo["usuarios"], {"cliente": 1, "validador": 1, "admin": 2})
            self.assertEqual(resumo["ingressos"], {"emitidos": 2, "usados": 1, "cancelados": 0,
                                                   "disponiveis": 1})
            self.assertEqual(resumo["leituras"], {"aceito": 1, "recusado": 1, "indeterminado": 0})
            self.assertEqual(resumo["filas"][0]["ocupacao"], 1)

            usuarios = api.get("/admin/usuarios", headers=adm).json()
            self.assertEqual(usuarios["total"], 4)
            self.assertNotIn("senha", json.dumps(usuarios).lower().replace("senha-de", ""))
            self.assertEqual(api.get("/admin/usuarios?busca=ver", headers=adm).json()["itens"][0]["login"],
                             "vera")

            leituras = api.get("/admin/leituras", headers=adm).json()["itens"]
            self.assertEqual([(l["eventId"], l["resultado"], l["motivo"], l["validadorId"]) for l in leituras],
                             [("l2", "recusado", "rosto-nao-confere", "vera"), ("l1", "aceito", None, "vera")])
            self.assertEqual(api.get("/admin/movimentos?tipo=contagem", headers=adm).json()["total"], 1)
            self.assertEqual(api.get("/admin/estados", headers=adm).json()["itens"][0]["esperaSegundos"], 20)
            self.assertTrue(any(h["entradas"] == 1 for h in api.get("/admin/historico", headers=adm).json()))
            self.assertEqual(api.get("/admin/historico?minutos=0", headers=adm).status_code, 422)  # repassado
            self.assertEqual(api.get("/admin/movimentos", headers=ana).status_code, 403)

            # Foto: só com link temporário, e quem abriu fica registrado.
            link = api.post("/admin/leituras/l1/foto", headers=adm).json()
            self.assertIn("leituras/l1.jpg", link["url"])
            self.assertEqual(api.post("/admin/leituras/l2/foto", headers=adm).status_code, 404)

            # Gestão: papéis e cancelamento.
            self.assertEqual(api.put("/admin/usuarios/adm/papel", json={"papel": "cliente"},
                                     headers=adm).status_code, 409)  # o próprio papel
            self.assertEqual(api.put("/admin/usuarios/ana/papel", json={"papel": "dono"},
                                     headers=adm).status_code, 422)
            self.assertEqual(api.put("/admin/usuarios/ana/papel", json={"papel": "validador"},
                                     headers=adm).status_code, 200)
            self.assertEqual(api.put("/admin/usuarios/adm2/papel", json={"papel": "cliente"},
                                     headers=adm).status_code, 200)
            # O token de adm2 ainda diz admin, mas o banco não: perde o acesso na hora.
            self.assertEqual(api.get("/admin/resumo", headers=adm2).status_code, 403)

            self.assertEqual(api.post("/admin/ingressos/AAAA00000001/cancelar", json={"motivo": "teste"},
                                      headers=adm).status_code, 409)  # já usado
            cancelado = api.post("/admin/ingressos/AAAA00000002/cancelar",
                                 json={"motivo": "pedido do cliente"}, headers=adm).json()
            self.assertEqual(cancelado["situacao"], "cancelado")
            self.assertEqual(api.get("/admin/ingressos?situacao=cancelado", headers=adm).json()["total"], 1)

            auditoria = api.get("/admin/auditoria", headers=adm).json()["itens"]
            self.assertEqual([(a["acao"], a["alvo"]) for a in reversed(auditoria)],
                             [("ver-foto", "l1"), ("mudar-papel", "ana"), ("mudar-papel", "adm2"),
                              ("cancelar-ingresso", "AAAA00000002")])

            # Ao vivo: o que chega do broker, validado.
            self.assertEqual(api.get("/admin/ao-vivo", headers=ana).status_code, 403)
            ao_vivo.filas_ao_vivo.clear()
            ao_vivo.mensagens_recentes.clear()
            momento = ao_vivo.agora_local()
            ms = int(momento.timestamp() * 1000)
            def mensagem(tipo, source, payload):
                return json.dumps(evento(tipo, source, payload, timestamp=ms)).encode()

            # A tentativa de leitura aparece, sem a referência da foto.
            leitura = ao_vivo.registrar_mensagem("fila/fila-a/leitura", mensagem(
                "leitura", "backend", {"filaId": "fila-a", "fotoRef": "leituras/x.jpg", "ingressoId": "AAAA00000001"}))
            self.assertEqual(leitura["event_type"], "leitura")
            self.assertNotIn("fotoRef", ao_vivo.filas_ao_vivo["fila-a"]["ultima_leitura"])
            self.assertFalse(ao_vivo.registrar_mensagem("fila/fila-a/estado", mensagem(
                "estado", "processador", {"filaId": "fila-b"})))
            self.assertFalse(ao_vivo.registrar_mensagem("fila/fila-a/heartbeat", b"lixo"))
            # Status de outro componente no tópico do backend: recusado.
            self.assertFalse(ao_vivo.registrar_mensagem("sistema/backend/status", mensagem(
                "status", "produtor", {"online": False})))
            ao_vivo.registrar_mensagem("fila/fila-a/heartbeat", mensagem(
                "heartbeat", "produtor", {"filaId": "fila-a"}), momento)
            ao_vivo.registrar_mensagem("fila/fila-a/estado", mensagem(
                "estado", "processador", {"filaId": "fila-a", "semaforo": "livre", "ocupacao": 0}),
                momento)
            ao_vivo.registrar_mensagem("sistema/produtor/status", mensagem(
                "status", "produtor", {"online": False}), momento)
            ao_vivo.registrar_mensagem("fila/fila-a/reacao", mensagem(
                "reacao", "consumidor", {"filaId": "fila-a", "resultadoId": "l1-resultado",
                                         "resultado": "aceito", "acao": "liberar"}), momento)
            ao_vivo.rejeitadas.clear()
            ao_vivo.registrar_mensagem("sistema/processador/rejeitado", mensagem(
                "rejeitado", "processador", {"topico": "fila/fila-a/saida", "motivo": "duplicado"}), momento)
            situacao = api.get("/admin/ao-vivo", headers=adm).json()
            fila = situacao["filas"][0]
            self.assertEqual((fila["filaId"], fila["estado"]["semaforo"], fila["ultimaReacao"]["acao"]),
                             ("fila-a", "livre", "liberar"))
            self.assertEqual([(c["source"], c["online"]) for c in situacao["componentes"]],
                             [("produtor", False)])
            self.assertEqual([(m["source"], m["tipo"]) for m in situacao["mensagens"]],
                             [("processador", "rejeitado"), ("consumidor", "reacao"), ("produtor", "status"),
                              ("processador", "estado"), ("backend", "leitura")])
            self.assertNotIn("fotoRef", situacao["mensagens"][-1]["payload"])
            self.assertEqual(api.get("/admin/ao-vivo", headers=adm).json()["rejeitadas"], {"duplicado": 1})
            depois = ao_vivo.situacao_atual(True, momento + timedelta(
                seconds=ao_vivo.LIMITE_SEM_HEARTBEAT_SEGUNDOS + 1))
            self.assertFalse(depois["filas"][0]["enlaceAtivo"])

        # Ingresso cancelado não entra, mesmo com o rosto certo.
        self.assertEqual(estado.registrar_resultado("l3", "fila-a", agora + 2, "AAAA00000002", "aceito",
                                                    usuario_id="ana", validador_id="vera")[:2],
                         ("recusado", "ingresso-cancelado"))
        motor.dispose()


if __name__ == "__main__":
    unittest.main()
