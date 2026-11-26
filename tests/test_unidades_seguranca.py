"""Testes unitários do limite de login, do registro das recusas, das recusas do broker
e das métricas, sem banco nem broker.

O comportamento com o banco filas_teste está em test_seguranca.py.
"""

import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from apoio_backend import carregar_backend
from observabilidade import recusas_broker


def requisicao(host="10.0.0.1", metodo="POST", rota="/sessoes", **estado):
    return SimpleNamespace(client=SimpleNamespace(host=host) if host else None, method=metodo,
                           url=SimpleNamespace(path=rota), state=SimpleNamespace(**estado),
                           app=SimpleNamespace(state=SimpleNamespace(chave_jwt="k" * 32)))


class LimitadorUnidadeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seg = carregar_backend().seguranca

    def setUp(self):
        self.limite = self.seg.Limitador(janela=60)

    def test_libera_ate_o_maximo_e_informa_a_espera(self):
        for instante in (0, 10, 20):
            self.assertEqual(self.limite.reservar([("k", 3)], agora=instante), 0)
        self.assertEqual(self.limite.reservar([("k", 3)], agora=30), 31)  # a de 0 s sai aos 60 s
        self.assertEqual(self.limite.reservar([("k", 3)], agora=60), 0)   # saiu da janela

    def test_nao_marca_nenhuma_chave_se_uma_estourar(self):
        self.limite.reservar([("login", 1)], agora=0)
        self.assertGreater(self.limite.reservar([("login", 1), ("ip", 5)], agora=1), 0)
        self.assertNotIn("ip", {c for c, m in self.limite.marcas.items() if m})

    def test_esquecer_devolver_e_limpar(self):
        for _ in range(2):
            self.limite.reservar([("a", 5), ("b", 5)], agora=0)
        self.limite.esquecer("a")
        self.limite.devolver("b")
        self.limite.devolver("nao-existe")  # não falha
        self.assertEqual((self.limite.marcas.get("a"), len(self.limite.marcas["b"])), (None, 1))
        self.limite.limpar()
        self.assertEqual(self.limite.marcas, {})

    def test_descarta_chaves_antigas_quando_acumula(self):
        self.limite.marcas = {f"login-{i}": __import__("collections").deque([0]) for i in range(10001)}
        self.limite.reservar([("novo", 5)], agora=100)
        self.assertEqual(set(self.limite.marcas), {"novo"})

    def test_concorrencia_nao_passa_do_maximo(self):
        liberadas = []
        def tentar():
            if self.limite.reservar([("k", 5)]) == 0:
                liberadas.append(1)
        threads = [threading.Thread(target=tentar) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(liberadas), 5)


class LoginLimitadoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seg = carregar_backend().seguranca

    def setUp(self):
        self.seg.logins.limpar()
        self.addCleanup(self.seg.logins.limpar)

    def test_limite_por_login_e_por_endereco(self):
        for _ in range(self.seg.MAXIMO_POR_LOGIN):
            self.assertEqual(self.seg.reservar_login("ip", "ana"), 0)
        self.assertGreater(self.seg.reservar_login("ip", "ana"), 0)
        self.assertEqual(self.seg.reservar_login("outro-ip", "ana"), 0)  # por endereço e login
        self.assertEqual(self.seg.reservar_login("ip", "bia"), 0)

        self.seg.logins.limpar()
        for i in range(self.seg.MAXIMO_POR_ENDERECO):
            self.assertEqual(self.seg.reservar_login("ip", f"login-{i}"), 0)
        self.assertGreater(self.seg.reservar_login("ip", "login-novo"), 0)

    def test_login_aceito_devolve_a_tentativa(self):
        for _ in range(self.seg.MAXIMO_POR_LOGIN - 1):
            self.seg.reservar_login("ip", "ana")
        self.seg.reservar_login("ip", "ana")
        self.seg.login_aceito("ip", "ana")
        self.assertNotIn(("ip", "ana"), self.seg.logins.marcas)
        self.assertEqual(len(self.seg.logins.marcas["ip"]), self.seg.MAXIMO_POR_LOGIN - 1)

    def test_endereco_de(self):
        self.assertEqual(self.seg.endereco_de(requisicao("1.2.3.4")), "1.2.3.4")
        self.assertEqual(self.seg.endereco_de(requisicao(None)), "desconhecido")


class RegistrarNegadoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seg = carregar_backend().seguranca

    def setUp(self):
        self.seg.registros.limpar()
        self.addCleanup(self.seg.registros.limpar)
        self.sessao = MagicMock()
        self.fabrica = patch.object(self.seg, "sessao_backend")
        fabrica = self.fabrica.start()
        self.addCleanup(self.fabrica.stop)

        @contextmanager
        def begin():
            yield self.sessao
        fabrica.begin.side_effect = begin

    def gravado(self):
        sql, valores = self.sessao.execute.call_args.args
        self.assertIs(sql, self.seg.INSERIR)
        return valores

    def test_tipo_pelo_status_e_pelo_login(self):
        casos = (
            (requisicao(login_tentado="ana"), 401, "login-recusado", "ana"),
            (requisicao(login_tentado="ana"), 429, "login-bloqueado", "ana"),
            (requisicao(metodo="GET", rota="/eu"), 401, "nao-autenticado", None),
            (requisicao(metodo="GET", rota="/admin/resumo", usuario_id="u1"), 403, "acesso-negado", None),
        )
        for pedido, status, tipo, login in casos:
            self.seg.registrar_negado(pedido, status)
            valores = self.gravado()
            self.assertEqual((valores["tipo"], valores["login"]), (tipo, login), status)
        self.assertEqual(valores["usuario_id"], "u1")

    def test_grava_so_os_campos_permitidos_e_corta_os_longos(self):
        self.seg.registrar_negado(requisicao(metodo="X" * 50, rota="/" + "a" * 500), 401)
        valores = self.gravado()
        self.assertEqual(set(valores), {"tipo", "login", "usuario_id", "endereco", "metodo", "rota"})
        self.assertEqual((len(valores["metodo"]), len(valores["rota"])), (10, 200))
        self.assertEqual(valores["endereco"], "10.0.0.1")

    def test_limite_de_registros_por_endereco(self):
        with patch.object(self.seg, "MAXIMO_REGISTROS_POR_MINUTO", 2):
            for _ in range(5):
                self.seg.registrar_negado(requisicao(), 401)
            self.seg.registrar_negado(requisicao("outro"), 401)
        self.assertEqual(self.sessao.execute.call_count, 3)

    def test_falha_no_banco_nao_derruba_a_resposta(self):
        self.sessao.execute.side_effect = RuntimeError("banco fora")
        with patch("builtins.print") as mostrar:
            self.seg.registrar_negado(requisicao(login_tentado="ana"), 401)
        self.assertIn("login-recusado", mostrar.call_args.args[0])
        self.assertNotIn("banco fora", mostrar.call_args.args[0])


class AppSegurancaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = carregar_backend()

    def setUp(self):
        self.app.seguranca.logins.limpar()
        self.addCleanup(self.app.seguranca.logins.limpar)

    def test_middleware_registra_so_401_403_e_429(self):
        api = TestClient(self.app.app)  # sem o ciclo de vida: não conecta ao broker
        token = self.app.admin.sessao_de_admin.__globals__["emitir_token"]("u1", "cliente", "k" * 32)
        cliente = {"Authorization": f"Bearer {token}"}
        leitura = {"ingressoId": "A" * 12, "filaId": "fila-a", "foto": "x" * 100}
        for _ in range(self.app.seguranca.MAXIMO_POR_LOGIN):
            self.app.seguranca.reservar_login("testclient", "ana")
        with patch.object(self.app.app.state, "chave_jwt", "k" * 32, create=True), \
             patch.object(self.app.seguranca, "registrar_negado") as registrar:
            self.assertEqual(api.get("/eu").status_code, 401)
            self.assertEqual(api.post("/leituras", json=leitura, headers=cliente).status_code, 403)
            self.assertEqual(api.post("/sessoes", json={"login": "ana", "senha": "x"}).status_code, 429)
            self.assertEqual(api.get("/nao-existe").status_code, 404)
            self.assertEqual(api.post("/sessoes", json={}).status_code, 422)
        self.assertEqual([c.args[1] for c in registrar.call_args_list], [401, 403, 429])

    def test_entrar_bloqueado_nem_consulta_o_banco(self):
        pedido = requisicao("ip")
        for _ in range(self.app.seguranca.MAXIMO_POR_LOGIN):
            self.app.seguranca.reservar_login("ip", "ana")
        with patch.object(self.app, "sessao_backend") as banco:
            with self.assertRaises(HTTPException) as erro:
                self.app.entrar(self.app.Credenciais(login="ana", senha="x"), pedido)
        banco.assert_not_called()
        self.assertEqual(erro.exception.status_code, 429)
        self.assertGreater(int(erro.exception.headers["Retry-After"]), 0)
        self.assertEqual(pedido.state.login_tentado, "ana")

    def test_entrar_recusado_e_aceito(self):
        usuario = SimpleNamespace(usuario_id="u1", papel="cliente", senha_hash="h")
        banco = MagicMock()
        banco.return_value.__enter__.return_value.scalar.return_value = usuario
        pedido = requisicao("ip")
        with patch.object(self.app, "sessao_backend", banco), \
             patch.object(self.app, "autenticar_hash", side_effect=[False, True]):
            with self.assertRaises(HTTPException) as erro:
                self.app.entrar(self.app.Credenciais(login="ana", senha="x"), pedido)
            self.assertEqual(erro.exception.status_code, 401)
            self.assertIn(("ip", "ana"), self.app.seguranca.logins.marcas)
            resposta = self.app.entrar(self.app.Credenciais(login="ana", senha="y"), pedido)
        self.assertEqual(resposta["papel"], "cliente")
        self.assertNotIn(("ip", "ana"), self.app.seguranca.logins.marcas)  # falhas zeradas

    def test_sessao_guarda_quem_pediu(self):
        aut = self.app.admin.sessao_de_admin.__globals__["sessao"].__globals__
        pedido = requisicao()
        credencial = SimpleNamespace(credentials=aut["emitir_token"]("u9", "cliente", "k" * 32))
        aut["sessao"](pedido, credencial)
        self.assertEqual(pedido.state.usuario_id, "u9")


class RecusasBrokerUnidadeTest(unittest.TestCase):
    def setUp(self):
        recusas_broker.recusas.clear()
        self.addCleanup(recusas_broker.recusas.clear)

    def test_interpretar(self):
        recusa = recusas_broker.interpretar(
            "1795662520: Client hacker [172.20.0.1:47188] disconnected: not authorised.")
        self.assertEqual((recusa["motivo"], recusa["usuario"], recusa["endereco"]),
                         ("credencial-recusada", "hacker", "172.20.0.1:47188"))
        self.assertEqual(recusa["momento"], datetime.fromtimestamp(1795662520).astimezone())
        sem_tls = recusas_broker.interpretar(
            "1: Client 172.20.0.1 [172.20.0.1:47184] disconnected: Protocol error.")
        self.assertEqual((sem_tls["motivo"], sem_tls["usuario"]), ("sem-tls-ou-protocolo", None))
        for linha in ("1: Client produtor [1.1.1.1:2] disconnected: exceeded timeout.",
                      "1: New client connected from 1.1.1.1:2 as produtor",
                      "Client x [1:2] disconnected: not authorised.",  # sem horário
                      "", "lixo"):
            self.assertIsNone(recusas_broker.interpretar(linha), linha)

    def test_situacao_por_janela(self):
        agora = datetime(2026, 11, 26, 12, 0).astimezone()
        def recusa(minutos, motivo="credencial-recusada", usuario="hacker"):
            return {"momento": agora - timedelta(minutes=minutos), "motivo": motivo,
                    "usuario": usuario, "endereco": "1.1.1.1:2"}
        recusas_broker.recusas.extend([recusa(90), recusa(30, usuario="validador"),
                                       recusa(5, "sem-tls-ou-protocolo", None)])
        with patch.object(recusas_broker, "ARQUIVO", Path("/nao/existe")):
            situacao = recusas_broker.situacao(agora)
        self.assertEqual((situacao["total"], situacao["logDisponivel"]), (2, False))
        self.assertEqual(situacao["porMotivo"], {"credencial-recusada": 1, "sem-tls-ou-protocolo": 1})
        self.assertEqual(situacao["porUsuario"], {"validador": 1})
        self.assertEqual(len(situacao["recentes"]), 3)  # as recentes não dependem da janela
        self.assertEqual(situacao["recentes"][0]["motivo"], "sem-tls-ou-protocolo")

    def test_recentes_limitadas_a_20(self):
        for i in range(30):
            recusas_broker.registrar_linhas([f"{1795662000 + i}: Client u{i} [1.1.1.1:{i}] disconnected: not authorised."])
        recentes = recusas_broker.situacao()["recentes"]
        self.assertEqual((len(recentes), recentes[0]["usuario"]), (20, "u29"))

    def test_primeira_leitura_comeca_perto_do_fim(self):
        linha = b"1795662520: Client velho [1.1.1.1:1] disconnected: not authorised.\n"
        nova = b"1795662521: Client novo [1.1.1.1:2] disconnected: not authorised.\n"
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "mosquitto.log"
            arquivo.write_bytes(linha * 50 + nova)
            parar = threading.Event()
            with patch.object(recusas_broker, "LER_DO_FIM_BYTES", len(nova) + 10), \
                 patch.object(recusas_broker, "INTERVALO_SEGUNDOS", 0.01), \
                 patch.object(recusas_broker.time, "sleep", side_effect=lambda _: parar.set()):
                recusas_broker.acompanhar(arquivo, parar)
        # A linha cortada no começo do trecho é descartada; só a nova entra.
        self.assertEqual([r["usuario"] for r in recusas_broker.recusas], ["novo"])

    def test_arquivo_trocado_e_lido_do_inicio(self):
        linha = b"1795662520: Client a [1.1.1.1:1] disconnected: not authorised.\n"
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "mosquitto.log"
            arquivo.write_bytes(linha)
            voltas = iter(range(3))
            parar = threading.Event()

            def depois_da_volta(_):
                volta = next(voltas)
                if volta == 0:  # o log foi substituído por outro arquivo (outro inode)
                    arquivo.unlink()
                    arquivo.write_bytes(linha.replace(b"Client a", b"Client b") * 2)
                elif volta == 1:
                    parar.set()
            with patch.object(recusas_broker.time, "sleep", side_effect=depois_da_volta):
                recusas_broker.acompanhar(arquivo, parar)
        self.assertEqual([r["usuario"] for r in recusas_broker.recusas], ["a", "b", "b"])

    def test_erro_de_leitura_nao_para_o_acompanhamento(self):
        parar = threading.Event()
        arquivo = MagicMock()
        arquivo.stat.side_effect = [PermissionError("sem acesso"), FileNotFoundError()]
        voltas = iter([None, parar.set])
        with patch.object(recusas_broker.time, "sleep", side_effect=lambda _: (next(voltas) or (lambda: None))()), \
             patch("builtins.print") as mostrar:
            recusas_broker.acompanhar(arquivo, parar)
        self.assertIn("sem acesso", mostrar.call_args.args[0])
        self.assertEqual(arquivo.stat.call_count, 2)

    def test_iniciar_sobe_uma_thread_daemon(self):
        with patch.object(recusas_broker.threading, "Thread") as thread:
            recusas_broker.iniciar()
        self.assertTrue(thread.call_args.kwargs["daemon"])
        thread.return_value.start.assert_called_once()


class MetricasUnidadeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict("os.environ", {"FILAS_DB": "filas_teste"}):
            from observabilidade import app, historico
        cls.app, cls.historico = app, historico

    def consultar(self, *linhas):
        s = MagicMock()
        s.execute.return_value.one.side_effect = linhas
        sessao = MagicMock()
        sessao.return_value.__enter__.return_value = s
        with patch.object(self.historico, "sessao", sessao):
            return self.historico.metricas(minutos=60)

    def test_arredonda_e_calcula_a_idade_da_pendente(self):
        antiga = datetime.now(timezone.utc) - timedelta(seconds=42)
        dados = self.consultar((3, 250.4, 200.5, 480.6, 500.0), (1, 4), (2, antiga))
        self.assertEqual(dados["leituraAteDecisao"],
                         {"quantidade": 3, "mediaMs": 250, "p50Ms": 200, "p95Ms": 481, "maximoMs": 500})
        self.assertEqual(dados["semResposta"], {"noPeriodo": 1, "total": 4})
        self.assertEqual(dados["saidaPendente"]["quantidade"], 2)
        self.assertAlmostEqual(dados["saidaPendente"]["maisAntigaSegundos"], 42, delta=2)

    def test_sem_dados(self):
        dados = self.consultar((0, None, None, None, None), (0, 0), (0, None))
        self.assertEqual(dados["leituraAteDecisao"]["p50Ms"], None)
        self.assertEqual(dados["saidaPendente"], {"quantidade": 0, "maisAntigaSegundos": None})

    def test_ao_vivo_inclui_as_recusas_do_broker(self):
        with patch.object(self.app.cliente_mqtt, "is_connected", return_value=True), \
             patch.object(recusas_broker, "situacao", return_value={"total": 7}):
            self.assertEqual(self.app.agora()["recusasBroker"], {"total": 7})

    def test_rota_valida_o_periodo(self):
        with TestClient(self.app.app) as api:
            self.assertEqual(api.get("/metricas?minutos=0").status_code, 422)
            self.assertEqual(api.get("/metricas?minutos=2000").status_code, 422)


class AdminSegurancaUnidadeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.admin = carregar_backend().admin

    def test_rotas_novas_e_tipo_validado(self):
        caminhos = {r.path for r in self.admin.rotas.routes}
        self.assertTrue({"/admin/metricas", "/admin/seguranca"} <= caminhos)
        app = carregar_backend().app
        api = TestClient(app)
        self.assertEqual(api.get("/admin/seguranca").status_code, 401)  # sem token
        app.dependency_overrides[self.admin.sessao_de_admin] = lambda: {"sub": "adm"}
        self.addCleanup(app.dependency_overrides.clear)
        with patch.object(self.admin, "sessao_painel") as banco:
            self.assertEqual(api.get("/admin/seguranca?tipo=qualquer").status_code, 422)
        banco.assert_not_called()  # o tipo inválido nem chega ao banco

if __name__ == "__main__":
    unittest.main()
