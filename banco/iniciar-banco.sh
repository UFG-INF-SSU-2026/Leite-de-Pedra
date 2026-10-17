#!/usr/bin/env bash
set -euo pipefail

RAIZ_PROJETO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v docker >/dev/null 2>&1; then
    echo "Docker não instalado. Instale o Docker (ou colima) para subir o TimescaleDB." >&2
    exit 1
fi

if [[ ! -f "$RAIZ_PROJETO/.local/banco/admin.password" ]]; then
    echo "Banco ainda não configurado. Execute banco/configurar-banco.sh." >&2
    exit 1
fi

exec docker compose -f "$RAIZ_PROJETO/banco/docker-compose.yml" up -d --wait
