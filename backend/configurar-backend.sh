#!/usr/bin/env bash
# Emite o certificado HTTPS do backend com a CA do projeto e gera a chave que
# assina os tokens do app. Uso: configurar-backend.sh [ip-da-maquina-na-rede]
set -euo pipefail

RAIZ_PROJETO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASTA_MQTT="$RAIZ_PROJETO/.local/mqtt"
PASTA_BACKEND="$RAIZ_PROJETO/.local/backend"

if [[ "$#" -gt 1 || ( "$#" -eq 1 && ! "$1" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ) ]]; then
    echo "Uso: $0 [ip-da-maquina-na-rede]" >&2
    exit 1
fi
if [[ ! -f "$PASTA_MQTT/ca.key" ]]; then
    echo "CA do projeto ausente. Execute broker/configurar-seguranca.sh primeiro." >&2
    exit 1
fi
if [[ -e "$PASTA_BACKEND/jwt.key" ]]; then
    echo "O backend já foi configurado em $PASTA_BACKEND; nada foi alterado." >&2
    exit 1
fi

nomes="DNS:localhost,IP:127.0.0.1"
if [[ "$#" -eq 1 ]]; then nomes="$nomes,IP:$1"; fi

mkdir -p "$PASTA_BACKEND"
chmod 700 "$PASTA_BACKEND"
umask 077

openssl req -new -newkey rsa:2048 -sha256 -nodes \
    -subj "/CN=localhost" \
    -addext "subjectAltName=$nomes" \
    -addext "basicConstraints=critical,CA:FALSE" \
    -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
    -addext "extendedKeyUsage=serverAuth" \
    -keyout "$PASTA_BACKEND/servidor.key" \
    -out "$PASTA_BACKEND/servidor.csr"

openssl x509 -req -sha256 -days 825 \
    -in "$PASTA_BACKEND/servidor.csr" \
    -CA "$PASTA_MQTT/ca.crt" \
    -CAkey "$PASTA_MQTT/ca.key" \
    -CAcreateserial -CAserial "$PASTA_BACKEND/ca.srl" \
    -copy_extensions copy \
    -out "$PASTA_BACKEND/servidor.crt"

openssl rand -hex 32 > "$PASTA_BACKEND/jwt.key"

rm "$PASTA_BACKEND/servidor.csr" "$PASTA_BACKEND/ca.srl"
chmod 600 "$PASTA_BACKEND"/*
echo "Certificado HTTPS ($nomes) e chave dos tokens criados em $PASTA_BACKEND."
