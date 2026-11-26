"""Hash de senha com scrypt, usado pelo backend do app e do dashboard."""

import hashlib
import hmac
import secrets


def gerar_hash_senha(senha, sal=None):
    sal = sal or secrets.token_bytes(16)
    resumo = hashlib.scrypt(senha.encode(), salt=sal, n=2**14, r=8, p=1)
    return f"scrypt${sal.hex()}${resumo.hex()}"


def senha_confere(senha, hash_guardado):
    try:
        _, sal, _ = hash_guardado.split("$")
        return hmac.compare_digest(gerar_hash_senha(senha, bytes.fromhex(sal)), hash_guardado)
    except (ValueError, AttributeError):
        return False


_HASH_PARA_USUARIO_INEXISTENTE = gerar_hash_senha(secrets.token_hex(8))


def autenticar_hash(senha, hash_guardado):
    """Confere a senha gastando o mesmo tempo quando o usuário não existe (hash None)."""
    confere = senha_confere(senha, hash_guardado or _HASH_PARA_USUARIO_INEXISTENTE)
    return hash_guardado is not None and confere
