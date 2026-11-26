#!/usr/bin/env bash
# Cria, num banco existente, a tabela dos logins recusados e acessos negados
# (banco/seguranca.sql) em filas e filas_teste. Idempotente.
set -euo pipefail

RAIZ_PROJETO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTEINER=leite-de-pedra-banco

for banco in filas filas_teste; do
    docker exec -i -u postgres "$CONTEINER" psql -v ON_ERROR_STOP=1 -q -d "$banco" \
        -c 'SET client_min_messages = warning;' -f - < "$RAIZ_PROJETO/banco/seguranca.sql"
done
echo "Registro de logins recusados e acessos negados criado."
