#!/usr/bin/env bash
set -euo pipefail

RAIZ_PROJETO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASTA_MQTT="$RAIZ_PROJETO/.local/mqtt"
PASTA_BANCO="$RAIZ_PROJETO/.local/banco"

if ! command -v openssl >/dev/null 2>&1; then
    echo "Erro: comando 'openssl' não encontrado." >&2
    exit 1
fi

if [[ ! -f "$PASTA_MQTT/ca.key" ]]; then
    echo "CA do projeto ausente. Execute broker/configurar-seguranca.sh primeiro." >&2
    exit 1
fi

if [[ -e "$PASTA_BANCO/admin.password" ]]; then
    echo "O banco já foi configurado em $PASTA_BANCO." >&2
    echo "Para preservar as credenciais existentes, nada foi alterado." >&2
    exit 1
fi

mkdir -p "$PASTA_BANCO"
chmod 700 "$PASTA_BANCO"
umask 077

openssl req -new -newkey rsa:2048 -sha256 -nodes \
    -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,DNS:banco,IP:127.0.0.1" \
    -addext "basicConstraints=critical,CA:FALSE" \
    -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
    -addext "extendedKeyUsage=serverAuth" \
    -keyout "$PASTA_BANCO/servidor.key" \
    -out "$PASTA_BANCO/servidor.csr"

openssl x509 -req -sha256 -days 825 \
    -in "$PASTA_BANCO/servidor.csr" \
    -CA "$PASTA_MQTT/ca.crt" \
    -CAkey "$PASTA_MQTT/ca.key" \
    -CAcreateserial -CAserial "$PASTA_BANCO/ca.srl" \
    -copy_extensions copy \
    -out "$PASTA_BANCO/servidor.crt"

for papel in admin processador backend painel observador; do
    openssl rand -hex 24 > "$PASTA_BANCO/$papel.password"
done

rm "$PASTA_BANCO/servidor.csr" "$PASTA_BANCO/ca.srl"
chmod 600 "$PASTA_BANCO"/*

echo "Certificado e credenciais do banco criados em $PASTA_BANCO."
echo "Os arquivos estão ignorados pelo Git e são exclusivos do usuário atual."
