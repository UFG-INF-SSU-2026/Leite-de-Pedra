"""Configuração segura e contrato das mensagens, compartilhados pelos clientes MQTT do projeto."""

import json
import os
import ssl
import time
import uuid
from pathlib import Path


RAIZ_PROJETO = Path(__file__).resolve().parent
PASTA_SEGREDOS_PADRAO = RAIZ_PROJETO / ".local" / "mqtt"
PAPEIS = {"produtor", "consumidor", "processador", "observador", "validador", "backend"}


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


TAMANHO_MAXIMO_ID = 128


# ---------- contrato das mensagens (docs/ARQUITETURA.md, "Contrato das mensagens") ----------

def evento(event_type, source, payload, correlation_id=None, event_id=None, timestamp=None):
    """Monta uma mensagem no contrato comum; sem correlation_id, ela abre uma operação nova."""
    event_id = event_id or uuid.uuid4().hex
    return {
        "event_id": event_id,
        "correlation_id": correlation_id or event_id,
        "event_type": event_type,
        "source": source,
        "timestamp": int(time.time() * 1000) if timestamp is None else timestamp,
        "payload": payload,
    }


def momento_valido(momento):
    return isinstance(momento, int) and not isinstance(momento, bool) and 0 < momento < 10**14


def ler_evento(topico, conteudo):
    """Devolve a mensagem se ela seguir o contrato e combinar com o tópico; senão, None.

    fila/{filaId}/{tipo}: payload.filaId igual ao tópico. sistema/{source}/{tipo}:
    source igual ao tópico. Nos dois, event_type igual ao último nível.
    """
    try:
        mensagem = json.loads(conteudo)
    except ValueError:  # inclui UTF-8 inválido
        return None
    partes = topico.split("/")
    if not isinstance(mensagem, dict) or len(partes) != 3 or partes[0] not in ("fila", "sistema"):
        return None
    ids = (mensagem.get(c) for c in ("event_id", "correlation_id", "source"))
    if (not all(isinstance(i, str) and 0 < len(i) <= TAMANHO_MAXIMO_ID for i in ids)
            or mensagem.get("event_type") != partes[2]
            or not momento_valido(mensagem.get("timestamp"))
            or not isinstance(mensagem.get("payload"), dict)):
        return None
    dono = mensagem["payload"].get("filaId") if partes[0] == "fila" else mensagem["source"]
    return mensagem if dono == partes[1] else None


# ---------- presença: sistema/{usuario}/status ----------

def topico_status(usuario):
    return f"sistema/{usuario}/status"


def _status(usuario, online):
    return json.dumps(evento("status", usuario, {"online": online}))


def desconectar(client, papel):
    """Avisa que saiu e desconecta: o broker só manda o Last Will quando a conexão cai."""
    usuario = os.getenv("MQTT_USERNAME", papel)
    # Vai antes do DISCONNECT na mesma conexão; não precisa esperar o PUBACK.
    client.publish(topico_status(usuario), _status(usuario, False), qos=1, retain=True)
    client.disconnect()


def conectar(client, papel, assincrono=False):
    """Autentica, ativa a validação TLS e conecta um cliente Paho.

    Registra o Last Will (offline, retido) e publica online a cada conexão,
    antes de chamar o on_connect do cliente: defina-o antes de conectar.
    """
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
    # A ACL só deixa cada usuário escrever no próprio sistema/{usuario}/status.
    client.will_set(topico_status(usuario), _status(usuario, False), qos=1, retain=True)
    ao_conectar_do_cliente = client.on_connect

    def ao_conectar(cliente, userdata, flags, reason_code, properties):
        if reason_code == 0:
            cliente.publish(topico_status(usuario), _status(usuario, True), qos=1, retain=True)
        if ao_conectar_do_cliente:
            ao_conectar_do_cliente(cliente, userdata, flags, reason_code, properties)

    client.on_connect = ao_conectar

    host = os.getenv("MQTT_HOST", "localhost")
    porta = int(os.getenv("MQTT_PORT", "8883"))
    if assincrono:
        client.connect_async(host, porta, 60)
    else:
        client.connect(host, porta, 60)
