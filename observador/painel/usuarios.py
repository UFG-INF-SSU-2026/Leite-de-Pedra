import getpass
import hashlib
import hmac
import json
import secrets
import sys

from .configuracao import ARQUIVO_CHAVE_JWT, ARQUIVO_USUARIOS, TAMANHO_MINIMO_SENHA


def gerar_hash_senha(senha, sal=None):
    sal = sal or secrets.token_bytes(16)
    resumo = hashlib.scrypt(senha.encode(), salt=sal, n=2**14, r=8, p=1)
    return f"scrypt${sal.hex()}${resumo.hex()}"


def senha_confere(senha, hash_guardado):
    try:
        _, sal, _ = hash_guardado.split("$")
        return hmac.compare_digest(gerar_hash_senha(senha, bytes.fromhex(sal)), hash_guardado)
    except ValueError:
        return False


def carregar_usuarios():
    try:
        return json.loads(ARQUIVO_USUARIOS.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


HASH_PARA_USUARIO_INEXISTENTE = gerar_hash_senha(secrets.token_hex(8))


def autenticar(usuario, senha):
    hash_guardado = carregar_usuarios().get(usuario)
    confere = senha_confere(senha, hash_guardado or HASH_PARA_USUARIO_INEXISTENTE)
    return hash_guardado is not None and confere


def criar_usuario(nome):
    if not ARQUIVO_CHAVE_JWT.exists():
        sys.exit("Execute observador/configurar-painel.sh primeiro.")
    senha = getpass.getpass(f"Senha para {nome}: ")
    if len(senha) < TAMANHO_MINIMO_SENHA:
        sys.exit(f"A senha precisa ter pelo menos {TAMANHO_MINIMO_SENHA} caracteres.")
    if senha != getpass.getpass("Repita a senha: "):
        sys.exit("As senhas não conferem.")
    usuarios = carregar_usuarios()
    usuarios[nome] = gerar_hash_senha(senha)
    ARQUIVO_USUARIOS.write_text(json.dumps(usuarios, indent=2), encoding="utf-8")
    ARQUIVO_USUARIOS.chmod(0o600)
    print(f"Usuário {nome} salvo em {ARQUIVO_USUARIOS}.")
