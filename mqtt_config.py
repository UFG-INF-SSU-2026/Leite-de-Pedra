"""Configuração segura compartilhada pelos clientes MQTT do projeto."""

import os
import ssl
from pathlib import Path


RAIZ_PROJETO = Path(__file__).resolve().parent
PASTA_SEGREDOS_PADRAO = RAIZ_PROJETO / ".local" / "mqtt"
PAPEIS = {"produtor", "sinalizador", "processador", "observador", "validador"}


def _senha_de(papel):
    senha_ambiente = os.getenv("MQTT_PASSWORD")
    if senha_ambiente:
        return senha_ambiente

    arquivo = Path(
        os.getenv(
            "MQTT_PASSWORD_FILE",
            str(PASTA_SEGREDOS_PADRAO / f"{papel}.password"),
        )
    )
    try:
        senha = arquivo.read_text(encoding="utf-8").strip()
    except FileNotFoundError as erro:
        raise RuntimeError(
            f"Credencial MQTT não encontrada em {arquivo}. "
            "Execute broker/configurar-seguranca.sh primeiro."
        ) from erro
    if not senha:
        raise RuntimeError(f"A credencial MQTT em {arquivo} está vazia")
    return senha


def conectar(client, papel, assincrono=False):
    """Autentica, ativa a validação TLS e conecta um cliente Paho."""
    if papel not in PAPEIS:
        raise ValueError(f"Papel MQTT desconhecido: {papel}")

    usuario = os.getenv("MQTT_USERNAME", papel)
    ca = Path(os.getenv("MQTT_CA", str(PASTA_SEGREDOS_PADRAO / "ca.crt")))
    if not ca.is_file():
        raise RuntimeError(
            f"CA MQTT não encontrada em {ca}. "
            "Execute broker/configurar-seguranca.sh primeiro."
        )

    contexto_tls = ssl.create_default_context(cafile=str(ca))
    contexto_tls.minimum_version = ssl.TLSVersion.TLSv1_2

    client.username_pw_set(usuario, _senha_de(papel))
    client.tls_set_context(contexto_tls)

    host = os.getenv("MQTT_HOST", "localhost")
    porta = int(os.getenv("MQTT_PORT", "8883"))
    if assincrono:
        client.connect_async(host, porta, 60)
    else:
        client.connect(host, porta, 60)
