import ssl
import sys
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from . import ao_vivo, historico, paginas, sessao, usuarios
from .configuracao import (ARQUIVO_CERTIFICADO, ARQUIVO_CHAVE_TLS, INTERVALO_HISTORICO_SEGUNDOS,
                           INTERVALO_MAXIMO_ATUALIZACAO_SEGUNDOS, NOME_COOKIE, PORTA)

CABECALHOS_SEGURANCA = {
    "Content-Security-Policy": "default-src 'none'; style-src 'self'; script-src 'self'; "
                               "connect-src 'self'; form-action 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Strict-Transport-Security": "max-age=31536000",
}
TAMANHO_MAXIMO_FORMULARIO = 1024
ATRASO_APOS_LOGIN_RECUSADO_SEGUNDOS = 1


def formatar_evento(nome, html):
    linhas = "".join(f"data: {linha}\n" for linha in html.splitlines())
    return f"event: {nome}\n{linhas}\n".encode("utf-8")


class RequisicaoPainel(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def enviar_cabecalhos(self, codigo, tipo, extras=()):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        for nome, valor in [*CABECALHOS_SEGURANCA.items(), *extras]:
            self.send_header(nome, valor)

    def responder(self, codigo, corpo, tipo="text/html; charset=utf-8", extras=()):
        if isinstance(corpo, str):
            corpo = corpo.encode("utf-8")
        self.enviar_cabecalhos(codigo, tipo, extras)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def redirecionar(self, destino, extras=()):
        self.responder(303, b"", extras=[("Location", destino), *extras])

    def usuario_logado(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        if NOME_COOKIE not in cookie:
            return None
        return sessao.usuario_do_token(cookie[NOME_COOKIE].value, self.server.chave_jwt)

    def do_GET(self):
        caminho = self.path.split("?", 1)[0]
        if caminho in paginas.ARQUIVOS_ESTATICOS:
            self.responder(200, *paginas.ler_estatico(caminho))
        elif caminho == "/login":
            self.responder(200, paginas.renderizar_login())
        elif self.usuario_logado() is None:
            self.redirecionar("/login")
        elif caminho == "/":
            self.responder(200, paginas.renderizar_painel(
                self.usuario_logado(), ao_vivo.situacao_atual(), historico.consultar_historico()))
        elif caminho == "/atualizacoes":
            self.transmitir_atualizacoes()
        else:
            self.responder(404, "Não encontrado", "text/plain; charset=utf-8")

    def transmitir_atualizacoes(self):
        self.enviar_cabecalhos(200, "text/event-stream; charset=utf-8")
        self.end_headers()
        ultimo_ao_vivo = ultimo_historico = None
        proxima_consulta_historico = 0
        try:
            while self.usuario_logado() is not None:
                if time.monotonic() >= proxima_consulta_historico:
                    html_historico = paginas.renderizar_historico(historico.consultar_historico())
                    proxima_consulta_historico = time.monotonic() + INTERVALO_HISTORICO_SEGUNDOS
                    if html_historico != ultimo_historico:
                        self.wfile.write(formatar_evento("historico", html_historico))
                        ultimo_historico = html_historico
                html_ao_vivo = paginas.renderizar_ao_vivo(ao_vivo.situacao_atual())
                if html_ao_vivo != ultimo_ao_vivo:
                    self.wfile.write(formatar_evento("ao-vivo", html_ao_vivo))
                    ultimo_ao_vivo = html_ao_vivo
                self.wfile.write(b": aguardando\n\n")
                self.wfile.flush()
                ao_vivo.esperar_mudanca(INTERVALO_MAXIMO_ATUALIZACAO_SEGUNDOS)
            self.wfile.write(formatar_evento("sessao-expirada", ""))
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass

    def do_POST(self):
        if self.path == "/sair":
            self.redirecionar("/login", [("Set-Cookie", sessao.cookie_de_saida())])
        elif self.path == "/login":
            self.fazer_login()
        else:
            self.responder(404, "Não encontrado", "text/plain; charset=utf-8")

    def ler_formulario_login(self):
        tamanho = int(self.headers.get("Content-Length", "0"))
        if not 0 < tamanho <= TAMANHO_MAXIMO_FORMULARIO:
            raise ValueError
        campos = parse_qs(self.rfile.read(tamanho).decode("utf-8"))
        return campos["usuario"][0][:64], campos["senha"][0][:256]

    def fazer_login(self):
        try:
            usuario, senha = self.ler_formulario_login()
        except (ValueError, KeyError, UnicodeDecodeError):
            self.responder(400, paginas.renderizar_login("Informe usuário e senha."))
            return
        if not usuarios.autenticar(usuario, senha):
            print(f"Login recusado para {usuario!r} de {self.client_address[0]}")
            time.sleep(ATRASO_APOS_LOGIN_RECUSADO_SEGUNDOS)
            self.responder(401, paginas.renderizar_login("Usuário ou senha inválidos."))
            return
        token = sessao.emitir_token(usuario, self.server.chave_jwt)
        self.redirecionar("/", [("Set-Cookie", sessao.cookie_de_sessao(token))])


def contexto_tls():
    contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    contexto.minimum_version = ssl.TLSVersion.TLSv1_2
    contexto.load_cert_chain(ARQUIVO_CERTIFICADO, ARQUIVO_CHAVE_TLS)
    return contexto


def iniciar():
    if not ARQUIVO_CERTIFICADO.exists():
        sys.exit("Painel não configurado. Execute observador/configurar-painel.sh.")
    if not usuarios.carregar_usuarios():
        sys.exit("Nenhum usuário. Crie um com: python3 -m observador.painel --criar-usuario <nome>")
    ao_vivo.iniciar_assinatura()
    servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), RequisicaoPainel)
    servidor.chave_jwt = sessao.ler_chave_jwt()
    servidor.socket = contexto_tls().wrap_socket(servidor.socket, server_side=True)
    print(f"Painel disponível em https://localhost:{PORTA}")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
        ao_vivo.encerrar_assinatura()
