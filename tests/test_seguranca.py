"""Limite de tentativas de login, registro das recusas e métricas da observabilidade."""

import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select

from apoio_backend import carregar_backend
from apoio_banco import cadastrar, motor_teste
from estado_filas import EstadoFilas
from modelos import EventoSeguranca, Movimento, Usuario, de_milissegundos, fabrica_de_sessoes
from mqtt_config import evento
from senhas import gerar_hash_senha


def usuario(usuario_id, papel="cliente"):
    return Usuario(usuario_id=usuario_id, login=usuario_id, nome=usuario_id.title(), papel=papel,
                   senha_hash=gerar_hash_senha(f"senha-de-{usuario_id}"), face_id=f"face-{usuario_id}")


class LimitadorTest(unittest.TestCase):
    def test_janela_deslizante_e_reserva_tudo_ou_nada(self):
        limite = carregar_backend().seguranca.Limitador(janela=60)
        for instante in range(3):
            self.assertEqual(limite.reservar([("a", 3), ("ip", 10)], agora=instante), 0)
        self.assertEqual(limite.reservar([("a", 3), ("ip", 10)], agora=10), 51)  # a primeira sai aos 60
        self.assertEqual(len(limite.marcas["ip"]), 3)  # a recusada não conta no endereço
        self.assertEqual(limite.reservar([("a", 3)], agora=61), 0)
        limite.esquecer("a")
        limite.devolver("ip")
        self.assertEqual((limite.marcas.get("a"), len(limite.marcas["ip"])), (None, 2))


class LoginTest(unittest.TestCase):
    def setUp(self):
        self.motor = motor_teste()
        self.app = carregar_backend()
        self.app.seguranca.logins.limpar()
        self.app.seguranca.registros.limpar()
        cadastrar(self.motor, usuario("ana"), usuario("adm", "admin"))
        self.addCleanup(self.motor.dispose)

    def registros(self):
        with fabrica_de_sessoes(self.motor)() as s:
            return [(e.tipo, e.login, e.usuario_id, e.rota) for e in
                    s.scalars(select(EventoSeguranca).order_by(EventoSeguranca.evento_seguranca_id))]

    def test_limite_de_tentativas_e_registro_das_recusas(self):
        maximo = self.app.seguranca.MAXIMO_POR_LOGIN
        with TestClient(self.app.app) as api:
            def entrar(login, senha):
                return api.post("/sessoes", json={"login": login, "senha": senha})

            # O login certo zera as falhas daquele login.
            for _ in range(maximo - 1):
                self.assertEqual(entrar("ana", "errada").status_code, 401)
            self.assertEqual(entrar("ana", "senha-de-ana").status_code, 200)
            for _ in range(maximo):
                self.assertEqual(entrar("ana", "errada").status_code, 401)
            bloqueado = entrar("ana", "senha-de-ana")  # nem a senha certa passa agora
            self.assertEqual(bloqueado.status_code, 429)
            self.assertGreater(int(bloqueado.headers["Retry-After"]), 0)
            # Outro login, do mesmo endereço, continua entrando.
            adm = {"Authorization": f"Bearer {entrar('adm', 'senha-de-adm').json()['token']}"}

            # Login que não existe conta do mesmo jeito: não revela quem existe.
            self.assertEqual(entrar("ninguem", "x").status_code, 401)
            self.assertEqual(api.get("/eu").status_code, 401)
            ana = self.app.seguranca.logins
            ana.limpar()
            token_ana = {"Authorization": f"Bearer {entrar('ana', 'senha-de-ana').json()['token']}"}
            self.assertEqual(api.get("/admin/seguranca", headers=token_ana).status_code, 403)

            registros = self.registros()
            esperado = ([("login-recusado", "ana", None, "/sessoes")] * (2 * maximo - 1)
                        + [("login-bloqueado", "ana", None, "/sessoes"),
                           ("login-recusado", "ninguem", None, "/sessoes"),
                           ("nao-autenticado", None, None, "/eu"),
                           ("acesso-negado", None, "ana", "/admin/seguranca")])
            self.assertEqual(registros, esperado)
            self.assertNotIn("errada", json.dumps(registros))

            # O admin vê as recusas na auditoria, com o filtro e o total das últimas 24 h.
            pagina = api.get("/admin/seguranca?tipo=login-bloqueado", headers=adm).json()
            self.assertEqual((pagina["total"], pagina["itens"][0]["login"]), (1, "ana"))
            self.assertEqual(pagina["ultimas24h"]["login-recusado"], 2 * maximo)
            self.assertEqual(api.get("/admin/seguranca?tipo=outro", headers=adm).status_code, 422)

    def test_tentativas_em_paralelo_nao_passam_do_limite(self):
        maximo = self.app.seguranca.MAXIMO_POR_LOGIN
        respostas = []
        with TestClient(self.app.app) as api:
            def tentar():
                respostas.append(api.post("/sessoes", json={"login": "ana", "senha": "errada"}).status_code)
            with patch.object(self.app, "ATRASO_APOS_LOGIN_RECUSADO_SEGUNDOS", 0.2):
                threads = [threading.Thread(target=tentar) for _ in range(maximo + 5)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
        self.assertEqual((respostas.count(401), respostas.count(429)), (maximo, 5))

    def test_registro_tem_limite_por_minuto(self):
        with patch.object(self.app.seguranca, "MAXIMO_REGISTROS_POR_MINUTO", 3), \
             TestClient(self.app.app) as api:
            for _ in range(6):
                api.get("/eu")
        self.assertEqual(len(self.registros()), 3)


class RecusasBrokerTest(unittest.TestCase):
    LOG = (b"1795662519: New connection from 172.20.0.1:47184 on port 8883.\n"
           b"1795662519: OpenSSL Error while trying to get the error[0]: wrong version number\n"
           b"1795662519: Client 172.20.0.1 [172.20.0.1:47184] disconnected: Protocol error.\n"
           b"1795662520: Client validador [172.20.0.1:47188] disconnected: not authorised.\n"
           b"1795662522: Client hacker [172.20.0.1:47194] disconnected: not authorised.\n"
           b"1795662530: Client produtor [172.20.0.1:47200] disconnected: exceeded timeout.\n")

    def setUp(self):
        from observabilidade import recusas_broker
        self.rb = recusas_broker
        self.rb.recusas.clear()
        self.addCleanup(self.rb.recusas.clear)

    def test_interpreta_so_as_recusas(self):
        novas = self.rb.registrar_linhas(self.LOG.decode().splitlines())
        self.assertEqual([(r["motivo"], r["usuario"]) for r in novas],
                         [("sem-tls-ou-protocolo", None), ("credencial-recusada", "validador"),
                          ("credencial-recusada", "hacker")])
        agora = novas[-1]["momento"] + timedelta(minutes=1)
        situacao = self.rb.situacao(agora)
        self.assertEqual((situacao["total"], situacao["porMotivo"], situacao["porUsuario"]),
                         (3, {"sem-tls-ou-protocolo": 1, "credencial-recusada": 2}, {"validador": 1, "hacker": 1}))
        self.assertEqual(situacao["recentes"][0]["usuario"], "hacker")
        self.assertEqual(self.rb.situacao(agora + timedelta(hours=2))["total"], 0)

    def test_acompanha_o_arquivo_crescendo_e_truncado(self):
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "mosquitto.log"
            parar = threading.Event()
            with patch.object(self.rb, "INTERVALO_SEGUNDOS", 0.02):
                leitor = threading.Thread(target=self.rb.acompanhar, args=(arquivo, parar))
                leitor.start()
                try:
                    time.sleep(0.1)  # o arquivo ainda não existe
                    linhas = self.LOG.splitlines(keepends=True)
                    arquivo.write_bytes(linhas[3][:20])  # linha pela metade: espera o resto
                    time.sleep(0.1)
                    self.assertEqual(len(self.rb.recusas), 0)
                    with arquivo.open("ab") as saida:
                        saida.write(linhas[3][20:] + linhas[4])
                    self.esperar(2)
                    arquivo.write_bytes(linhas[2])  # truncado: recomeça do início
                    self.esperar(3)
                finally:
                    parar.set()
                    leitor.join()
        self.assertEqual([r["motivo"] for r in self.rb.recusas],
                         ["credencial-recusada", "credencial-recusada", "sem-tls-ou-protocolo"])

    def esperar(self, quantidade):
        limite = time.monotonic() + 3
        while len(self.rb.recusas) < quantidade and time.monotonic() < limite:
            time.sleep(0.02)
        self.assertEqual(len(self.rb.recusas), quantidade)


class MetricasTest(unittest.TestCase):
    def test_leitura_ate_decisao_504_e_saida_pendente(self):
        motor = motor_teste()
        self.addCleanup(motor.dispose)
        with patch.dict("os.environ", {"FILAS_DB": "filas_teste"}):
            from observabilidade.app import app
        estado = EstadoFilas(motor)
        agora = int(time.time() * 1000)
        for i, demora in enumerate((100, 200, 300, 1000)):
            leitura = evento("leitura", "backend", {"filaId": "fila-a"}, event_id=f"l{i}",
                             timestamp=agora - 5000 + i)
            estado.aplicar("fila-a", leitura)
            mensagem = (lambda i: lambda *_: (f"l{i}-resultado", "fila/fila-a/resultado", "{}"))(i)
            estado.registrar_resultado(f"l{i}", "fila-a", leitura["timestamp"] + demora, "ING", "recusado",
                                       "ingresso-inexistente", mensagem=mensagem if i == 3 else None)
        # 504: o backend gravou o indeterminado; a leitura atrasada não entra no tempo.
        estado.aplicar("fila-a", evento("leitura", "backend", {"filaId": "fila-a"}, event_id="l9",
                                        timestamp=agora - 20000))
        with fabrica_de_sessoes(motor).begin() as s:
            s.add(Movimento(evento_id="l9", fila_id="fila-a", tipo="resultado",
                            momento=de_milissegundos(agora - 10000), resultado="indeterminado",
                            motivo="sem-resposta-processador", origem="backend"))
            s.add(Movimento(evento_id="l8", fila_id="fila-a", tipo="resultado",
                            momento=datetime.fromtimestamp(0).astimezone(), resultado="indeterminado",
                            motivo="sem-resposta-processador", origem="backend"))

        with TestClient(app) as api:
            dados = api.get("/metricas?minutos=60").json()
        self.assertEqual(dados["leituraAteDecisao"],
                         {"quantidade": 4, "mediaMs": 400, "p50Ms": 250, "p95Ms": 895, "maximoMs": 1000})
        self.assertEqual(dados["semResposta"], {"noPeriodo": 1, "total": 2})
        self.assertEqual(dados["saidaPendente"]["quantidade"], 1)
        self.assertLess(dados["saidaPendente"]["maisAntigaSegundos"], 60)


if __name__ == "__main__":
    unittest.main()
