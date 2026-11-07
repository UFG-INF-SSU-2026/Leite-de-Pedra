#!/usr/bin/env bash
# Prepara o docker-compose.yml: confere os segredos gerados pelos scripts de
# configuração, inclui os nomes dos serviços (broker, banco) nos certificados
# e grava o .env. Pode rodar de novo; só muda o que falta.
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"

for arquivo in .local/mqtt/ca.key .local/mqtt/mosquitto.passwd .local/banco/admin.password \
               .local/banco/painel.password .local/backend/jwt.key; do
    if [[ ! -e "$arquivo" ]]; then
        echo "Falta $arquivo. Rode antes os scripts de configuração do README" >&2
        echo "(broker/configurar-seguranca.sh, banco/configurar-banco.sh, backend/configurar-backend.sh)." >&2
        exit 1
    fi
done

# Reemite o certificado de servidor com a mesma CA quando falta o nome do
# serviço no Docker. A CA não muda: os ESP32 e os clientes continuam valendo.
reemitir() {
    local pasta=$1 base=$2 nomes=$3 exigido=$4
    if openssl x509 -in "$pasta/$base.crt" -noout -ext subjectAltName | grep -q "$exigido"; then
        return
    fi
    (
        umask 077
        openssl req -new -newkey rsa:2048 -sha256 -nodes -subj "/CN=localhost" \
            -addext "subjectAltName=$nomes" \
            -addext "basicConstraints=critical,CA:FALSE" \
            -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
            -addext "extendedKeyUsage=serverAuth" \
            -keyout "$pasta/$base.key.novo" -out "$pasta/$base.csr" 2>/dev/null
        openssl x509 -req -sha256 -days 825 -in "$pasta/$base.csr" \
            -CA .local/mqtt/ca.crt -CAkey .local/mqtt/ca.key \
            -CAcreateserial -CAserial "$pasta/ca.srl" -copy_extensions copy \
            -out "$pasta/$base.crt.novo" 2>/dev/null
        mv "$pasta/$base.key.novo" "$pasta/$base.key"
        mv "$pasta/$base.crt.novo" "$pasta/$base.crt"
        rm -f "$pasta/$base.csr" "$pasta/ca.srl"
    )
    echo "Certificado $pasta/$base.crt reemitido com $nomes."
}
reemitir .local/mqtt broker "DNS:localhost,DNS:host.wokwi.internal,DNS:broker,IP:127.0.0.1" "DNS:broker"
reemitir .local/banco servidor "DNS:localhost,DNS:banco,IP:127.0.0.1" "DNS:banco"

mkdir -p .local/mosquitto
chmod 600 broker/mosquitto.acl

if [[ ! -e .env ]]; then
    cat > .env <<EOF
# Lido pelo docker-compose.yml. Fora do Git.
HOST_UID=$(id -u)
HOST_GID=$(id -g)
AWS_DEFAULT_REGION=us-east-1
REKOGNITION_COLECAO=leite-de-pedra
FOTOS_BUCKET=
BACKEND_AWS_PROFILE=leite-de-pedra-admin
EOF
    chmod 600 .env
    echo ".env criado: preencha FOTOS_BUCKET e confira os perfis AWS."
fi
echo "Pronto: docker compose up -d --build"
