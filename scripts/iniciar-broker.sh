#!/usr/bin/env bash
set -euo pipefail

RAIZ_PROJETO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if command -v mosquitto >/dev/null 2>&1; then
    EXECUTAVEL_MOSQUITTO="$(command -v mosquitto)"
elif [[ -x /usr/sbin/mosquitto ]]; then
    EXECUTAVEL_MOSQUITTO=/usr/sbin/mosquitto
else
    echo "Broker não instalado. Instale o pacote 'mosquitto'." >&2
    exit 1
fi

if [[ ! -f "$RAIZ_PROJETO/.local/mqtt/mosquitto.passwd" ]]; then
    echo "Segurança ainda não configurada. Execute scripts/configurar-seguranca.sh." >&2
    exit 1
fi

cd "$RAIZ_PROJETO"
chmod 600 mosquitto.acl
exec "$EXECUTAVEL_MOSQUITTO" -c mosquitto.conf
