#!/usr/bin/env bash
# Atualiza um banco criado antes do app (só com filas, movimentos e estados):
# cria os papéis backend e painel, as tabelas de usuários, ingressos e
# auditoria em filas e filas_teste. Rodar uma vez; depois, adicionar-observador.sh.
set -euo pipefail

RAIZ_PROJETO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASTA_BANCO="$RAIZ_PROJETO/.local/banco"
CONTEINER=leite-de-pedra-banco
COMPOSE=(docker compose -f "$RAIZ_PROJETO/docker-compose.yml")
psql_como_postgres() { docker exec -i -u postgres "$CONTEINER" psql -v ON_ERROR_STOP=1 -q "$@"; }

for papel in backend painel; do
    if [[ ! -e "$PASTA_BANCO/$papel.password" ]]; then
        (umask 077; openssl rand -hex 24 > "$PASTA_BANCO/$papel.password")
    fi
done

# As senhas vão pela entrada padrão, não pela linha de comando.
psql_como_postgres -d postgres <<SQL
CREATE ROLE backend LOGIN PASSWORD '$(tr -d '\r\n' < "$PASTA_BANCO/backend.password")';
CREATE ROLE painel LOGIN PASSWORD '$(tr -d '\r\n' < "$PASTA_BANCO/painel.password")';
GRANT CONNECT ON DATABASE filas, filas_teste TO backend, painel;
SQL

for banco in filas filas_teste; do
    psql_como_postgres -d "$banco" < "$RAIZ_PROJETO/banco/ingressos.sql"
done

# O pg_hba.conf passou a aceitar backend e painel; reinicia para recarregá-lo.
"${COMPOSE[@]}" restart banco
"${COMPOSE[@]}" up -d --wait banco
echo "Papéis backend e painel e tabelas de usuários, ingressos e auditoria criados."
