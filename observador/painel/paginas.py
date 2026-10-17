from jinja2 import Environment, FileSystemLoader, select_autoescape

from .configuracao import MINUTOS_DE_HISTORICO, PASTA_PAINEL

ARQUIVOS_ESTATICOS = {
    "/painel.css": ("painel.css", "text/css; charset=utf-8"),
    "/painel.js": ("painel.js", "text/javascript; charset=utf-8"),
}


def formatar_hora(momento):
    return momento.astimezone().strftime("%H:%M:%S") if momento else "–"


def formatar_milissegundos(valor):
    return "–" if valor is None else f"{valor:.0f} ms"


def formatar_segundos(valor):
    return "–" if valor is None else f"{valor} s"


modelos = Environment(
    loader=FileSystemLoader(PASTA_PAINEL / "templates"),
    autoescape=select_autoescape(["html"]),
)
modelos.filters["hora"] = formatar_hora
modelos.filters["ms"] = formatar_milissegundos
modelos.filters["segundos"] = formatar_segundos


def ler_estatico(caminho):
    nome, tipo = ARQUIVOS_ESTATICOS[caminho]
    return (PASTA_PAINEL / "static" / nome).read_bytes(), tipo


def renderizar_login(erro=None):
    return modelos.get_template("login.html").render(erro=erro)


def renderizar_ao_vivo(situacao):
    return modelos.get_template("ao_vivo.html").render(**situacao)


def renderizar_historico(por_minuto):
    return modelos.get_template("historico.html").render(
        por_minuto=por_minuto, minutos=MINUTOS_DE_HISTORICO)


def renderizar_painel(usuario, situacao, por_minuto):
    return modelos.get_template("painel.html").render(
        usuario=usuario,
        ao_vivo=renderizar_ao_vivo(situacao),
        historico=renderizar_historico(por_minuto))
