#!/usr/bin/env bash
set -euo pipefail

RAIZ_PROJETO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASTA_MQTT="$RAIZ_PROJETO/.local/mqtt"
PASTA_PAINEL="$RAIZ_PROJETO/.local/painel"

if ! command -v openssl >/dev/null 2>&1; then
    echo "Erro: comando 'openssl' não encontrado." >&2
    exit 1
fi

if [[ ! -f "$PASTA_MQTT/ca.key" ]]; then
    echo "CA do projeto ausente. Execute broker/configurar-seguranca.sh primeiro." >&2
    exit 1
fi

if [[ -e "$PASTA_PAINEL/jwt.key" ]]; then
    echo "O painel já foi configurado em $PASTA_PAINEL." >&2
    echo "Para preservar as credenciais existentes, nada foi alterado." >&2
    exit 1
fi

mkdir -p "$PASTA_PAINEL"
chmod 700 "$PASTA_PAINEL"
umask 077

openssl req -new -newkey rsa:2048 -sha256 -nodes \
    -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
    -addext "basicConstraints=critical,CA:FALSE" \
    -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
    -addext "extendedKeyUsage=serverAuth" \
    -keyout "$PASTA_PAINEL/servidor.key" \
    -out "$PASTA_PAINEL/servidor.csr"

openssl x509 -req -sha256 -days 825 \
    -in "$PASTA_PAINEL/servidor.csr" \
    -CA "$PASTA_MQTT/ca.crt" \
    -CAkey "$PASTA_MQTT/ca.key" \
    -CAcreateserial -CAserial "$PASTA_PAINEL/ca.srl" \
    -copy_extensions copy \
    -out "$PASTA_PAINEL/servidor.crt"

openssl rand -hex 32 > "$PASTA_PAINEL/jwt.key"

rm "$PASTA_PAINEL/servidor.csr" "$PASTA_PAINEL/ca.srl"
chmod 600 "$PASTA_PAINEL"/*

echo "Certificado HTTPS e chave JWT do painel criados em $PASTA_PAINEL."
echo "Crie um usuário com: python3 -m observador.painel --criar-usuario <nome>"
