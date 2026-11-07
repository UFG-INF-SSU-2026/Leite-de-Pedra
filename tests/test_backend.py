"""Backend do app: cadastro com rosto, login, compra e leitura na catraca por validador."""

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from apoio_backend import carregar_backend, foto, rekognition, s3
from apoio_banco import cadastrar, motor_teste
from modelos import Usuario
from mqtt_config import evento, ler_evento
from senhas import gerar_hash_senha


class BackendTest(unittest.TestCase):
    def test_fluxo_do_app(self):
        motor = motor_teste()
        app_modulo = carregar_backend()
        rekognition.rostos.clear()
        s3.chaves.clear()

        with TestClient(app_modulo.app) as api:
            cadastro = {"login": "ana", "senha": "senha-da-ana", "nome": "Ana", "foto": foto("ana")}
            self.assertEqual(api.post("/usuarios", json=cadastro).status_code, 201)
            self.assertEqual(api.post("/usuarios", json=cadastro).status_code, 409)  # login repetido
            self.assertEqual(api.post("/usuarios", json={**cadastro, "login": "ana2"}).status_code,
                             409)  # mesmo rosto em outra conta
            self.assertEqual(api.post("/usuarios", json={**cadastro, "login": "ana3",
                                                          "foto": "não é base64" * 20}).status_code, 422)

            self.assertEqual(api.post("/sessoes", json={"login": "ana", "senha": "errada"}).status_code, 401)
            sessao = api.post("/sessoes", json={"login": "ana", "senha": "senha-da-ana"}).json()
            self.assertEqual(sessao["papel"], "cliente")
            ana = {"Authorization": f"Bearer {sessao['token']}"}

            ingresso = api.post("/ingressos", headers=ana).json()["ingressoId"]
            meus = api.get("/ingressos", headers=ana).json()
            self.assertEqual([(i["ingressoId"], i["usadoEm"]) for i in meus], [(ingresso, None)])

            leitura = {"ingressoId": ingresso, "filaId": "fila-a", "foto": foto("ana")}
            self.assertEqual(api.post("/leituras", json=leitura).status_code, 401)
            self.assertEqual(api.post("/leituras", json=leitura, headers=ana).status_code, 403)

            # Validador só existe pelo banco: o backend não consegue criar um.
            cadastrar(motor, Usuario(usuario_id="validador-1", login="vera", nome="Vera",
                                     senha_hash=gerar_hash_senha("senha-da-vera"), face_id="f-vera",
                                     papel="validador"))
            vera = {"Authorization": "Bearer " + api.post(
                "/sessoes", json={"login": "vera", "senha": "senha-da-vera"}).json()["token"]}

            publicadas = []

            def processador_falso(topico, conteudo, qos):
                publicadas.append((topico, json.loads(conteudo)))
                app_modulo.receber_resultado(evento(
                    "resultado", "processador", {"filaId": "fila-a", "resultado": "aceito"},
                    correlation_id=publicadas[-1][1]["correlation_id"]))

            with patch.object(app_modulo.cliente_mqtt, "is_connected", return_value=True), \
                 patch.object(app_modulo.cliente_mqtt, "publish", side_effect=processador_falso):
                resposta = api.post("/leituras", json=leitura, headers=vera)
            self.assertEqual(resposta.status_code, 200)
            self.assertEqual((resposta.json()["resultado"], resposta.json()["ingressoId"]),
                             ("aceito", ingresso))
            topico, enviada = publicadas[0]
            self.assertEqual(topico, "fila/fila-a/leitura")
            self.assertEqual(ler_evento(topico, json.dumps(enviada)), enviada)
            self.assertNotEqual(enviada["event_id"], enviada["correlation_id"])
            self.assertEqual(resposta.json()["eventId"], enviada["event_id"])
            dados = enviada["payload"]
            ana_id = api.get("/eu", headers=ana).json()["usuarioId"]
            self.assertEqual((enviada["source"], dados["validadorId"], dados["ingressoId"], dados["fotoRef"],
                              dados["reconhecimento"], dados["usuarioReconhecido"]),
                             ("backend", "validador-1", ingresso, s3.chaves[0], "reconhecido", ana_id))

            # Rosto fora da coleção e falha da AWS também viram leitura: quem decide é o processador.
            with patch.object(app_modulo.cliente_mqtt, "is_connected", return_value=True), \
                 patch.object(app_modulo.cliente_mqtt, "publish", side_effect=processador_falso):
                api.post("/leituras", json={**leitura, "foto": foto("desconhecido")}, headers=vera)
                with patch.object(rekognition, "search_faces_by_image", side_effect=RuntimeError("AWS fora")):
                    api.post("/leituras", json=leitura, headers=vera)
            self.assertEqual([(p["payload"]["reconhecimento"], "usuarioReconhecido" in p["payload"])
                              for _, p in publicadas[1:]],
                             [("nao-reconhecido", False), ("falha", False)])
            self.assertTrue(s3.chaves[0].startswith("leituras/"))
            self.assertEqual(api.get("/eu", headers=ana).json()["papel"], "cliente")
        motor.dispose()


if __name__ == "__main__":
    unittest.main()
