"""Testes unitários das funções puras e dos callbacks, sem banco nem broker.

As funções que consultam o banco (EstadoFilas, rotas do backend e do histórico)
ficam com os testes de integração (test_estado_filas, test_backend, test_admin).
"""

import base64
import io
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import jwt
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

import estado_filas
import modelos
import mqtt_config
import senhas
from apoio_backend import carregar_backend, rekognition, s3
from observabilidade import ao_vivo

CHAVE = "k" * 32


def requisicao(query=""):
    return SimpleNamespace(url=SimpleNamespace(query=query),
                           app=SimpleNamespace(state=SimpleNamespace(chave_jwt=CHAVE)))


def observabilidade():
    with patch.dict("os.environ", {"FILAS_DB": "filas_teste"}):  # nunca o banco filas
        from observabilidade import app, historico
    return app, historico



class SenhasTest(unittest.TestCase):
    def test_gerar_hash_senha(self):
        algoritmo, sal, resumo = senhas.gerar_hash_senha("segredo").split("$")
        self.assertEqual((algoritmo, len(sal), len(resumo)), ("scrypt", 32, 128))
        self.assertEqual(senhas.gerar_hash_senha("x", b"s" * 16), senhas.gerar_hash_senha("x", b"s" * 16))
        self.assertNotEqual(senhas.gerar_hash_senha("x"), senhas.gerar_hash_senha("x"))  # sal aleatório

    def test_senha_confere(self):
        guardado = senhas.gerar_hash_senha("segredo")
        self.assertTrue(senhas.senha_confere("segredo", guardado))
        self.assertFalse(senhas.senha_confere("outra", guardado))
        for invalido in ("lixo", "a$zz$b", None):
            self.assertFalse(senhas.senha_confere("segredo", invalido), invalido)

    def test_autenticar_hash(self):
        guardado = senhas.gerar_hash_senha("segredo")
        self.assertTrue(senhas.autenticar_hash("segredo", guardado))
        self.assertFalse(senhas.autenticar_hash("outra", guardado))
        self.assertFalse(senhas.autenticar_hash("segredo", None))  # usuário inexistente



class MqttConfigTest(unittest.TestCase):
    def test_senha_de(self):
        with patch.dict("os.environ", {"MQTT_PASSWORD": "do-ambiente"}):
            self.assertEqual(mqtt_config._senha_de("produtor"), "do-ambiente")
        with tempfile.TemporaryDirectory() as pasta, patch.dict("os.environ", {}, clear=True):
            arquivo = Path(pasta) / "senha"
            os.environ["MQTT_PASSWORD_FILE"] = str(arquivo)
            with self.assertRaisesRegex(RuntimeError, "não encontrada"):
                mqtt_config._senha_de("produtor")
            arquivo.write_text("  \n")
            with self.assertRaisesRegex(RuntimeError, "vazia"):
                mqtt_config._senha_de("produtor")
            arquivo.write_text(" do-arquivo\n")
            self.assertEqual(mqtt_config._senha_de("produtor"), "do-arquivo")

    def test_evento(self):
        antes = int(time.time() * 1000)
        novo = mqtt_config.evento("contagem", "produtor", {"filaId": "fila-a"})
        self.assertEqual(novo["correlation_id"], novo["event_id"])
        self.assertTrue(antes <= novo["timestamp"] <= int(time.time() * 1000))
        self.assertEqual(mqtt_config.evento("x", "y", {}, correlation_id="c", event_id="e", timestamp=0),
                         {"event_id": "e", "correlation_id": "c", "event_type": "x", "source": "y",
                          "timestamp": 0, "payload": {}})

    def test_momento_valido(self):
        for valido in (1, 1_700_000_000_000, 10**14 - 1):
            self.assertTrue(mqtt_config.momento_valido(valido), valido)
        for invalido in (0, -1, 10**14, True, 1.5, "1", None):
            self.assertFalse(mqtt_config.momento_valido(invalido), invalido)

    def test_ler_evento(self):
        # O contrato completo está em test_contrato; aqui, os casos de forma do tópico.
        status = mqtt_config.evento("status", "backend", {})
        self.assertEqual(mqtt_config.ler_evento("sistema/backend/status", json.dumps(status)), status)
        self.assertIsNone(mqtt_config.ler_evento("sistema/backend/status/x", json.dumps(status)))
        self.assertIsNone(mqtt_config.ler_evento("sistema/backend/status", "[1, 2]"))

    def test_topico_status(self):
        self.assertEqual(mqtt_config.topico_status("backend"), "sistema/backend/status")

    def test_status(self):
        mensagem = json.loads(mqtt_config._status("backend", True))
        self.assertEqual(mqtt_config.ler_evento("sistema/backend/status", json.dumps(mensagem)), mensagem)
        self.assertEqual(mensagem["payload"], {"online": True})

    def test_desconectar(self):
        cliente = MagicMock()
        with patch.dict("os.environ", {"MQTT_USERNAME": "outro"}):
            mqtt_config.desconectar(cliente, "backend")
        topico, conteudo = cliente.publish.call_args.args
        self.assertEqual((topico, json.loads(conteudo)["payload"]), ("sistema/outro/status", {"online": False}))
        self.assertEqual(cliente.publish.call_args.kwargs, {"qos": 1, "retain": True})
        cliente.disconnect.assert_called_once()

    def test_conectar(self):
        with self.assertRaisesRegex(ValueError, "desconhecido"):
            mqtt_config.conectar(MagicMock(), "intruso")
        with patch.dict("os.environ", {"MQTT_CA": "/nao/existe.crt"}):
            with self.assertRaisesRegex(RuntimeError, "CA MQTT"):
                mqtt_config.conectar(MagicMock(), "backend")

        with tempfile.NamedTemporaryFile() as ca, \
             patch.dict("os.environ", {"MQTT_CA": ca.name, "MQTT_PASSWORD": "senha", "MQTT_HOST": "broker",
                                       "MQTT_PORT": "1234"}), \
             patch("ssl.create_default_context"):
            on_connect_original = MagicMock()
            cliente = MagicMock(on_connect=on_connect_original)
            mqtt_config.conectar(cliente, "backend")
            cliente.username_pw_set.assert_called_once_with("backend", "senha")
            self.assertEqual(cliente.will_set.call_args.args[0], "sistema/backend/status")
            cliente.connect.assert_called_once_with("broker", 1234, 60)

            cliente.on_connect(cliente, None, None, 5, None)  # recusado: não se anuncia online
            cliente.publish.assert_not_called()
            cliente.on_connect(cliente, None, None, 0, None)
            self.assertEqual(json.loads(cliente.publish.call_args.args[1])["payload"], {"online": True})
            self.assertEqual(on_connect_original.call_count, 2)

            assincrono = MagicMock(on_connect=None)
            mqtt_config.conectar(assincrono, "backend", assincrono=True)
            assincrono.connect_async.assert_called_once_with("broker", 1234, 60)
            assincrono.on_connect(assincrono, None, None, 0, None)  # sem on_connect do cliente



class ModelosTest(unittest.TestCase):
    def test_criar_motor(self):
        with patch.dict("os.environ", {"FILAS_DB_PASSWORD": "senha", "FILAS_DB_HOST": "h",
                                       "FILAS_DB_PORT": "1"}):
            url = modelos.criar_motor("painel", banco="b").url
        self.assertEqual((url.username, url.password, url.host, url.port, url.database),
                         ("painel", "senha", "h", 1, "b"))
        self.assertEqual(url.query["sslmode"], "verify-full")
        with tempfile.TemporaryDirectory() as pasta, \
             patch.dict("os.environ", {"FILAS_DB_PASSWORD": ""}), \
             patch.object(modelos, "PASTA_SEGREDOS", Path(pasta)):
            with self.assertRaisesRegex(RuntimeError, "banco/configurar-banco.sh"):
                modelos.criar_motor("painel")

    def test_fabrica_de_sessoes(self):
        motor = MagicMock()
        fabrica = modelos.fabrica_de_sessoes(motor)
        self.assertIs(fabrica.kw["bind"], motor)
        self.assertFalse(fabrica.kw["expire_on_commit"])

    def test_de_e_em_milissegundos(self):
        self.assertEqual(modelos.de_milissegundos(0), datetime(1970, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(modelos.em_milissegundos(modelos.de_milissegundos(1_700_000_000_123)), 1_700_000_000_123)



class EstadoFilasUnidadeTest(unittest.TestCase):
    def test_travar_leitura(self):
        s = MagicMock()
        s.execute.return_value.first.return_value = None
        self.assertIsNone(estado_filas.travar_leitura(s, "e1"))
        self.assertEqual(s.execute.call_count, 2)  # a trava, depois a consulta

        s.execute.return_value.first.return_value = SimpleNamespace(
            resultado="aceito", motivo=None, momento=modelos.de_milissegundos(1234))
        self.assertEqual(estado_filas.travar_leitura(s, "e1"), ("aceito", None, 1234))

    def test_na_saida(self):
        s = MagicMock()
        estado_filas.EstadoFilas._na_saida(s, None, "aceito")
        s.execute.assert_not_called()
        mensagem = MagicMock(return_value=("e1", "fila/fila-a/resultado", "{}"))
        estado_filas.EstadoFilas._na_saida(s, mensagem, "aceito", None, 1)
        mensagem.assert_called_once_with("aceito", None, 1)
        s.execute.assert_called_once()



class AutenticacaoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        carregar_backend()
        from backend import autenticacao
        cls.aut = autenticacao

    def credencial(self, **dados):
        return SimpleNamespace(credentials=jwt.encode(dados, CHAVE, algorithm="HS256"))

    def test_ler_chave_jwt(self):
        with tempfile.TemporaryDirectory() as pasta, patch.object(self.aut, "PASTA_SEGREDOS", Path(pasta)):
            (Path(pasta) / "jwt.key").write_text(" chave\n")
            self.assertEqual(self.aut.ler_chave_jwt(), "chave")

    def test_emitir_token(self):
        dados = jwt.decode(self.aut.emitir_token("u1", "cliente", CHAVE), CHAVE, algorithms=["HS256"])
        self.assertEqual((dados["sub"], dados["papel"]), ("u1", "cliente"))
        self.assertEqual(dados["exp"] - dados["iat"], self.aut.DURACAO_TOKEN_SEGUNDOS)
        fixo = jwt.decode(self.aut.emitir_token("u1", "cliente", CHAVE, agora=time.time()), CHAVE,
                          algorithms=["HS256"])
        self.assertIsInstance(fixo["iat"], int)

    def test_sessao(self):
        agora = int(time.time())
        valido = {"sub": "u1", "papel": "cliente", "iat": agora, "exp": agora + 60}
        self.assertEqual(self.aut.sessao(requisicao(), self.credencial(**valido)), valido)
        invalidos = (None, self.credencial(**{**valido, "exp": agora - 1}),
                     self.credencial(sub="u1", papel="cliente", exp=agora + 60),  # sem iat
                     SimpleNamespace(credentials=jwt.encode(valido, "o" * 32, algorithm="HS256")))
        for credencial in invalidos:
            with self.assertRaises(HTTPException) as erro:
                self.aut.sessao(requisicao(), credencial)
            self.assertEqual(erro.exception.status_code, 401)

    def test_sessao_de_validador(self):
        dados = {"sub": "v1", "papel": "validador"}
        self.assertEqual(self.aut.sessao_de_validador(dados), dados)
        with self.assertRaises(HTTPException) as erro:
            self.aut.sessao_de_validador({"sub": "u1", "papel": "cliente"})
        self.assertEqual(erro.exception.status_code, 403)

    def test_sessao_de_admin(self):
        painel = MagicMock()
        papel_no_banco = painel.return_value.__enter__.return_value.scalar
        with patch.object(self.aut, "sessao_painel", painel):
            papel_no_banco.return_value = "admin"
            self.assertEqual(self.aut.sessao_de_admin({"sub": "a1", "papel": "admin"})["sub"], "a1")
            for token, banco in (("admin", "cliente"), ("cliente", "admin")):  # rebaixado; token de cliente
                papel_no_banco.return_value = banco
                with self.assertRaises(HTTPException) as erro:
                    self.aut.sessao_de_admin({"sub": "a1", "papel": token})
                self.assertEqual(erro.exception.status_code, 403)


class ServicosTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        carregar_backend()
        from backend import servicos
        cls.serv = servicos

    def esperar(self, correlacao):
        espera = [threading.Event(), None]
        self.serv.respostas[correlacao] = espera
        self.addCleanup(self.serv.respostas.pop, correlacao, None)
        return espera

    def test_receber_resultado(self):
        espera = self.esperar("c1")
        self.serv.receber_resultado({"correlation_id": "outra", "payload": {}})  # ninguém esperando
        self.assertFalse(espera[0].is_set())
        self.serv.receber_resultado({"correlation_id": "c1", "payload": {"resultado": "aceito"}})
        self.assertTrue(espera[0].is_set())
        self.assertEqual(espera[1], {"resultado": "aceito"})

    def test_ao_receber(self):
        espera = self.esperar("c2")
        estado = mqtt_config.evento("estado", "processador", {"filaId": "fila-a"}, correlation_id="c2")
        for topico, conteudo in (("fila/fila-a/estado", json.dumps(estado)), ("fila/fila-a/resultado", b"lixo")):
            self.serv.ao_receber(None, None, SimpleNamespace(topic=topico, payload=conteudo))
        self.assertFalse(espera[0].is_set())
        resultado = mqtt_config.evento("resultado", "processador", {"filaId": "fila-a", "resultado": "aceito"},
                                       correlation_id="c2")
        self.serv.ao_receber(None, None, SimpleNamespace(topic="fila/fila-a/resultado",
                                                         payload=json.dumps(resultado)))
        self.assertEqual(espera[1]["resultado"], "aceito")

    def test_ao_conectar(self):
        cliente = MagicMock()
        with patch("builtins.print"):
            self.serv.ao_conectar(cliente, None, None, 5, None)
            cliente.subscribe.assert_not_called()
            self.serv.ao_conectar(cliente, None, None, 0, None)
        cliente.subscribe.assert_called_once_with("fila/+/resultado", 1)


class AppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = carregar_backend()

    def test_raiz_e_middleware(self):
        api = TestClient(self.app.app)  # sem "with": não sobe o ciclo de vida (MQTT, JWT)
        resposta = api.get("/", follow_redirects=False)
        self.assertEqual((resposta.status_code, resposta.headers["location"]), (307, "/painel/"))
        self.assertEqual(resposta.headers["cache-control"], "no-store")
        self.assertIn("max-age", resposta.headers["strict-transport-security"])
        self.assertNotIn("content-security-policy", resposta.headers)
        self.assertIn("content-security-policy", api.get("/painel/nao-existe").headers)
        with patch.object(self.app, "TAMANHO_MAXIMO_CORPO", 10):
            self.assertEqual(api.post("/usuarios", content=b"x" * 11).status_code, 413)

    def test_decodificar_foto(self):
        for cabecalho in (b"\xff\xd8", b"\x89PNG"):
            foto = cabecalho + b"resto"
            self.assertEqual(self.app.decodificar_foto(base64.b64encode(foto).decode()), foto)
        for invalida in ("não é base64", base64.b64encode(b"GIF89a").decode()):
            with self.assertRaises(HTTPException) as erro:
                self.app.decodificar_foto(invalida)
            self.assertEqual(erro.exception.status_code, 422)

    def test_reconhecer(self):
        rekognition.rostos[b"rosto-ana"] = "u-ana"
        self.addCleanup(rekognition.rostos.pop, b"rosto-ana")
        self.assertEqual(self.app.reconhecer(b"rosto-ana"), ("reconhecido", "u-ana"))
        self.assertEqual(self.app.reconhecer(b"estranho"), ("nao-reconhecido", None))
        with patch.object(rekognition, "search_faces_by_image", side_effect=RuntimeError("AWS fora")), \
             patch("builtins.print"):
            self.assertEqual(self.app.reconhecer(b"rosto-ana"), ("falha", None))

    def test_apagar_foto(self):
        s3.limpar()
        self.app.apagar_foto("leituras/1.jpg")
        self.assertEqual(s3.apagadas, ["leituras/1.jpg"])
        with patch.object(s3, "delete_object", side_effect=RuntimeError("S3 fora")), patch("builtins.print"):
            self.app.apagar_foto("leituras/2.jpg")  # não propaga: a entrada já foi decidida

    def test_filas_agora(self):
        def fila(fila_id, semaforo, espera, ativo=True):
            return {"filaId": fila_id, "enlaceAtivo": ativo,
                    "estado": {"semaforo": semaforo, "ocupacao": 1, "tempoEsperaEstimado": espera}}
        casos = (  # melhor semáforo; entre iguais, menor espera, com a indeterminada por último
            ([fila("a", "livre", None), fila("b", "livre", 30), fila("c", "atencao", 0)], "b", "abc"),
            ([fila("a", "bloqueada", 5), fila("b", "livre", 1, ativo=False),
              {"filaId": "c", "enlaceAtivo": True, "estado": None}], "a", "a"),
            ([], None, ""),
        )
        for filas, recomendada, listadas in casos:
            with patch.object(self.app.admin, "da_observabilidade", return_value={"filas": filas}):
                resposta = self.app.filas_agora(requisicao(), None)
            self.assertEqual(resposta["recomendada"], recomendada)
            self.assertEqual("".join(f["filaId"] for f in resposta["filas"]), listadas)

    def test_encerrar_sem_resposta(self):
        payload = {"filaId": "fila-a", "ingressoId": "ING", "validadorId": "v1"}
        sessao = MagicMock()
        s = sessao.begin.return_value.__enter__.return_value
        with patch.object(self.app, "sessao_backend", sessao), \
             patch.object(self.app, "travar_leitura", return_value=("aceito", None, 1)):
            self.assertEqual(self.app.encerrar_sem_resposta("e1", "c1", payload),
                             {"resultado": "aceito", "motivo": None})
        s.add.assert_not_called()
        with patch.object(self.app, "sessao_backend", sessao), \
             patch.object(self.app, "travar_leitura", return_value=None):
            self.assertIsNone(self.app.encerrar_sem_resposta("e1", "c1", payload))
        gravado = s.add.call_args.args[0]
        self.assertEqual((gravado.resultado, gravado.motivo, gravado.origem, gravado.correlacao_id),
                         ("indeterminado", "sem-resposta-processador", "backend", "c1"))


class AdminUnidadeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        carregar_backend()
        from backend import admin
        cls.admin = admin

    def test_pagina(self):
        s = MagicMock()
        s.scalar.return_value = 7
        s.execute.return_value.all.return_value = [1, 2]
        consulta = select(modelos.Fila).order_by(modelos.Fila.fila_id)
        self.assertEqual(self.admin.pagina(s, consulta, 2, 4, lambda n: n * 10), {"total": 7, "itens": [10, 20]})
        executada = s.execute.call_args.args[0]
        self.assertEqual((executada._limit, executada._offset), (2, 4))

    def test_auditar(self):
        s = MagicMock()
        self.admin.auditar(s, "a1", "mudar-papel", "u1", {"de": "cliente"})
        linha = s.add.call_args.args[0]
        self.assertEqual((linha.admin_id, linha.acao, linha.alvo, linha.detalhe),
                         ("a1", "mudar-papel", "u1", {"de": "cliente"}))

    def test_usuario_json(self):
        u = modelos.Usuario(usuario_id="u1", login="ana", nome="Ana", papel="cliente", face_id="f",
                            senha_hash="segredo")
        self.assertEqual(self.admin.usuario_json(u), {"usuarioId": "u1", "login": "ana", "nome": "Ana",
                                                      "papel": "cliente", "faceId": "f", "criadoEm": None})

    def test_ingresso_json(self):
        agora = datetime.now(timezone.utc)
        casos = (({}, "disponivel"), ({"usado_em": agora}, "usado"),
                 ({"usado_em": agora, "cancelado_em": agora}, "cancelado"))
        for campos, situacao in casos:
            i = modelos.Ingresso(ingresso_id="ING", usuario_id="u1", **campos)
            convertido = self.admin.ingresso_json(i, dono={"login": "ana"})
            self.assertEqual((convertido["situacao"], convertido["dono"]), (situacao, {"login": "ana"}))

    def test_da_observabilidade(self):
        base = self.admin.servicos.URL_OBSERVABILIDADE
        with patch("urllib.request.urlopen", side_effect=lambda *_, **__: io.BytesIO(b'{"ok": 1}')) as abrir:
            self.assertEqual(self.admin.da_observabilidade("historico", requisicao("minutos=5")), {"ok": 1})
            self.assertEqual(abrir.call_args.args[0], f"{base}/historico?minutos=5")
            self.admin.da_observabilidade("ao-vivo", requisicao())
            self.assertEqual(abrir.call_args.args[0], f"{base}/ao-vivo")

        recusado = urllib.error.HTTPError("u", 422, "x", {}, io.BytesIO(b'{"detail": "minutos"}'))
        for erro, codigo, detalhe in ((recusado, 422, "minutos"),
                                      (urllib.error.URLError("fora"), 503, None)):
            with patch("urllib.request.urlopen", side_effect=erro), self.assertRaises(HTTPException) as falha:
                self.admin.da_observabilidade("historico", requisicao())
            self.assertEqual(falha.exception.status_code, codigo)
            if detalhe:
                self.assertEqual(falha.exception.detail, detalhe)

    def test_repassar(self):
        pedido = requisicao()
        with patch.object(self.admin, "da_observabilidade", return_value="ok") as repasse:
            self.assertEqual(self.admin._repassar("estados")(pedido), "ok")
        repasse.assert_called_once_with("estados", pedido)



class AoVivoTest(unittest.TestCase):
    def setUp(self):
        for estrutura in (ao_vivo.filas_ao_vivo, ao_vivo.componentes, ao_vivo.rejeitadas,
                          ao_vivo.mensagens_recentes):
            estrutura.clear()
        self.agora = ao_vivo.agora_local()

    def registrar(self, topico, tipo, source, payload, atraso_ms=250):
        momento = int(self.agora.timestamp() * 1000) - atraso_ms
        mensagem = mqtt_config.evento(tipo, source, payload, timestamp=momento)
        return ao_vivo.registrar_mensagem(topico, json.dumps(mensagem), self.agora)

    def test_agora_local(self):
        self.assertIsNotNone(ao_vivo.agora_local().tzinfo)

    def test_situacao_vazia(self):
        vazia = ao_vivo.situacao_vazia()
        self.assertTrue(all(v is None for v in vazia.values()))
        self.assertIsNot(vazia, ao_vivo.situacao_vazia())

    def test_registrar_mensagem_descarta(self):
        self.assertIsNone(ao_vivo.registrar_mensagem("fila/fila-a/estado", b"lixo"))
        self.assertIsNone(self.registrar("sistema/x/heartbeat", "heartbeat", "x", {}))
        self.assertIsNone(self.registrar("fila/fila-a/outro", "outro", "p", {"filaId": "fila-a"}))
        self.assertEqual((ao_vivo.filas_ao_vivo, len(ao_vivo.mensagens_recentes)), ({}, 0))

    def test_registrar_mensagem_sistema(self):
        self.registrar("sistema/backend/status", "status", "backend", {"online": True})
        self.registrar("sistema/produtor/status", "status", "produtor", {"online": "sim"})
        self.assertEqual({k: v["online"] for k, v in ao_vivo.componentes.items()},
                         {"backend": True, "produtor": False})
        self.assertIsNone(ao_vivo.mensagens_recentes[0]["latenciaMs"])  # Last Will tem horário velho
        for _ in range(2):
            self.registrar("sistema/processador/rejeitado", "rejeitado", "processador", {"motivo": "m" * 50})
        self.assertEqual(ao_vivo.rejeitadas, {"m" * 40: 2})

    def test_registrar_mensagem_fila(self):
        self.registrar("fila/fila-a/heartbeat", "heartbeat", "produtor", {"filaId": "fila-a"})
        self.assertEqual(ao_vivo.filas_ao_vivo["fila-a"]["ultimo_heartbeat"], self.agora)
        self.assertEqual(len(ao_vivo.mensagens_recentes), 0)  # heartbeat não polui o recente

        self.registrar("fila/fila-a/estado", "estado", "processador", {"filaId": "fila-a", "ocupacao": 2})
        self.assertEqual(ao_vivo.filas_ao_vivo["fila-a"]["estado"]["ocupacao"], 2)
        self.assertAlmostEqual(ao_vivo.mensagens_recentes[0]["latenciaMs"], 250, delta=1)

        self.registrar("fila/fila-a/leitura", "leitura", "backend", {"filaId": "fila-a", "fotoRef": "s3"})
        self.assertNotIn("fotoRef", ao_vivo.filas_ao_vivo["fila-a"]["ultima_leitura"])
        self.assertNotIn("fotoRef", ao_vivo.mensagens_recentes[0]["payload"])
        for tipo, chave in (("resultado", "ultimo_resultado"), ("reacao", "ultima_reacao"),
                            ("recomendacao", "recomendacao")):
            self.registrar(f"fila/fila-a/{tipo}", tipo, "processador", {"filaId": "fila-a", "x": tipo})
            self.assertEqual(ao_vivo.filas_ao_vivo["fila-a"][chave]["x"], tipo)
        self.assertEqual(ao_vivo.mensagens_recentes[0]["filaId"], "fila-a")

    def test_situacao_atual(self):
        for fila, segundos in (("fila-c", 9), ("fila-a", 5)):
            ao_vivo.filas_ao_vivo[fila] = {**ao_vivo.situacao_vazia(),
                                           "ultimo_heartbeat": self.agora - timedelta(seconds=segundos)}
        ao_vivo.filas_ao_vivo["fila-b"] = ao_vivo.situacao_vazia()
        situacao = ao_vivo.situacao_atual(True, self.agora)
        self.assertEqual([(f["filaId"], f["enlaceAtivo"]) for f in situacao["filas"]],
                         [("fila-a", True), ("fila-b", False), ("fila-c", False)])
        self.assertIsNone(situacao["filas"][1]["segundosSemHeartbeat"])
        self.assertTrue(situacao["brokerConectado"])


class ObservabilidadeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, cls.historico = observabilidade()

    def test_pagina(self):
        s = MagicMock()
        s.scalar.return_value = 1
        s.execute.return_value.all.return_value = ["m"]
        self.assertEqual(self.historico.pagina(s, select(modelos.Fila), 1, 0, str.upper), {"total": 1, "itens": ["M"]})

    def test_movimento_json(self):
        m = modelos.Movimento(evento_id="e1", tipo="resultado", fila_id="fila-a", resultado="aceito",
                              correlacao_id="c1", origem="processador")
        convertido = self.historico.movimento_json(m)
        self.assertEqual((convertido["eventId"], convertido["correlationId"], convertido["resultado"]),
                         ("e1", "c1", "aceito"))

    def test_ao_conectar(self):
        cliente = MagicMock()
        with patch("builtins.print"):
            self.app.ao_conectar(cliente, None, None, 5, None)
            cliente.subscribe.assert_not_called()
            self.app.ao_conectar(cliente, None, None, 0, None)
        topicos = dict(cliente.subscribe.call_args.args[0])
        self.assertIn("sistema/+/rejeitado", topicos)
        self.assertIn("fila/+/estado", topicos)

    def test_ao_receber(self):
        with patch.object(ao_vivo, "registrar_mensagem") as registrar:
            self.app.ao_receber(None, None, SimpleNamespace(topic="fila/fila-a/estado", payload=b"{}"))
        registrar.assert_called_once_with("fila/fila-a/estado", b"{}")

    def test_agora(self):
        with patch.object(self.app.cliente_mqtt, "is_connected", return_value=False):
            self.assertFalse(self.app.agora()["brokerConectado"])


if __name__ == "__main__":
    unittest.main()
