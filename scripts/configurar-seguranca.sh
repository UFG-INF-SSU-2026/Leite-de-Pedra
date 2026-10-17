#!/usr/bin/env bash
set -euo pipefail

RAIZ_PROJETO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASTA_MQTT="$RAIZ_PROJETO/.local/mqtt"
RENOVAR_CERTIFICADOS=0

ADICIONAR_VALIDADOR=0
ADICIONAR_SINALIZADOR=0
if [[ "${1:-}" == "--renovar-certificados" && "$#" -eq 1 ]]; then
    RENOVAR_CERTIFICADOS=1
elif [[ "${1:-}" == "--adicionar-validador" && "$#" -eq 1 ]]; then
    ADICIONAR_VALIDADOR=1
elif [[ "${1:-}" == "--adicionar-sinalizador" && "$#" -eq 1 ]]; then
    ADICIONAR_SINALIZADOR=1
elif [[ "$#" -ne 0 ]]; then
    echo "Uso: $0 [--renovar-certificados|--adicionar-validador|--adicionar-sinalizador]" >&2
    exit 1
fi

for comando in openssl mosquitto_passwd; do
    if ! command -v "$comando" >/dev/null 2>&1; then
        echo "Erro: comando '$comando' não encontrado." >&2
        exit 1
    fi
done

if [[ "$RENOVAR_CERTIFICADOS" -eq 1 && ! -f "$PASTA_MQTT/mosquitto.passwd" ]]; then
    echo "Credenciais ainda não configuradas; execute o script sem argumentos." >&2
    exit 1
fi

if [[ "$ADICIONAR_VALIDADOR" -eq 1 || "$ADICIONAR_SINALIZADOR" -eq 1 ]]; then
    papel=validador
    if [[ "$ADICIONAR_SINALIZADOR" -eq 1 ]]; then papel=sinalizador; fi
    if [[ ! -f "$PASTA_MQTT/mosquitto.passwd" || -e "$PASTA_MQTT/$papel.password" ]]; then
        echo "Credenciais ausentes ou $papel já configurado." >&2
        exit 1
    fi
    umask 077
    senha="$(openssl rand -hex 24)"
    printf '%s\n' "$senha" > "$PASTA_MQTT/$papel.password"
    mosquitto_passwd -b "$PASTA_MQTT/mosquitto.passwd" "$papel" "$senha"
    echo "$papel adicionado. Reinicie o broker."
    exit 0
fi

if [[ "$RENOVAR_CERTIFICADOS" -eq 0 && -e "$PASTA_MQTT/mosquitto.passwd" ]]; then
    echo "A segurança MQTT já foi configurada em $PASTA_MQTT." >&2
    echo "Para preservar as credenciais existentes, nada foi alterado." >&2
    exit 1
fi

mkdir -p "$PASTA_MQTT"
chmod 700 "$RAIZ_PROJETO/.local" "$PASTA_MQTT"
umask 077

openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 3650 \
    -subj "/CN=Leite de Pedra - CA de desenvolvimento" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -keyout "$PASTA_MQTT/ca.key" \
    -out "$PASTA_MQTT/ca.crt"

openssl req -new -newkey rsa:2048 -sha256 -nodes \
    -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,DNS:host.wokwi.internal,IP:127.0.0.1" \
    -addext "basicConstraints=critical,CA:FALSE" \
    -addext "keyUsage=critical,digitalSignature,keyEncipherment" \
    -addext "extendedKeyUsage=serverAuth" \
    -keyout "$PASTA_MQTT/broker.key" \
    -out "$PASTA_MQTT/broker.csr"

openssl x509 -req -sha256 -days 825 \
    -in "$PASTA_MQTT/broker.csr" \
    -CA "$PASTA_MQTT/ca.crt" \
    -CAkey "$PASTA_MQTT/ca.key" \
    -CAcreateserial \
    -copy_extensions copy \
    -out "$PASTA_MQTT/broker.crt"

if [[ "$RENOVAR_CERTIFICADOS" -eq 0 ]]; then
    primeiro=1
    for papel in produtor sinalizador processador observador validador; do
        senha="$(openssl rand -hex 24)"
        printf '%s\n' "$senha" > "$PASTA_MQTT/$papel.password"
        if [[ "$primeiro" -eq 1 ]]; then
            mosquitto_passwd -b -c "$PASTA_MQTT/mosquitto.passwd" "$papel" "$senha"
            primeiro=0
        else
            mosquitto_passwd -b "$PASTA_MQTT/mosquitto.passwd" "$papel" "$senha"
        fi
    done
fi

rm "$PASTA_MQTT/broker.csr" "$PASTA_MQTT/ca.srl"
chmod 600 "$PASTA_MQTT"/*

echo "CA e certificado criados em $PASTA_MQTT."
if [[ "$RENOVAR_CERTIFICADOS" -eq 0 ]]; then
    echo "Credenciais dos cinco papéis criadas em $PASTA_MQTT."
else
    echo "Credenciais preservadas. Reinicie o broker."
fi
echo "Os arquivos estão ignorados pelo Git e são exclusivos do usuário atual."
