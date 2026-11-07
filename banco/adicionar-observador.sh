#!/usr/bin/env bash
# Atualiza um banco criado antes da observabilidade: cria o papel observador
# (só leitura do que o processador grava), tira do papel painel o histórico
# operacional, que passou a ser da observabilidade, e cria a tabela saida
# (outbox) se faltar. Idempotente.
set -euo pipefail

RAIZ_PROJETO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASTA_BANCO="$RAIZ_PROJETO/.local/banco"
CONTEINER=leite-de-pedra-banco
psql_como_postgres() { docker exec -i -u postgres "$CONTEINER" psql -v ON_ERROR_STOP=1 -q "$@"; }

if [[ ! -e "$PASTA_BANCO/observador.password" ]]; then
    (umask 077; openssl rand -hex 24 > "$PASTA_BANCO/observador.password")
fi

# A senha vai pela entrada padrão, não pela linha de comando.
psql_como_postgres -d postgres <<SQL
DO \$\$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'observador') THEN
        CREATE ROLE observador LOGIN;
    END IF;
END \$\$;
ALTER ROLE observador PASSWORD '$(tr -d '\n' < "$PASTA_BANCO/observador.password")';
GRANT CONNECT ON DATABASE filas, filas_teste TO observador;
SQL

for banco in filas filas_teste; do
    psql_como_postgres -d "$banco" <<'SQL'
SET client_min_messages = warning;
CREATE TABLE IF NOT EXISTS saida (
    evento_id    TEXT        PRIMARY KEY,
    topico       TEXT        NOT NULL,
    conteudo     TEXT        NOT NULL,
    criado_em    TIMESTAMPTZ NOT NULL DEFAULT now(),
    publicado_em TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS saida_pendente ON saida (criado_em) WHERE publicado_em IS NULL;
GRANT SELECT, INSERT, UPDATE (publicado_em) ON saida TO processador;
ALTER TABLE movimentos ADD COLUMN IF NOT EXISTS correlacao_id TEXT;
ALTER TABLE movimentos ADD COLUMN IF NOT EXISTS origem TEXT;
GRANT USAGE ON SCHEMA public TO observador;
GRANT SELECT ON filas, movimentos, estados, movimentos_por_minuto, espera_por_minuto, saida
    TO observador;
REVOKE SELECT ON filas, estados, movimentos_por_minuto, espera_por_minuto, saida FROM painel;
SQL
done
psql_como_postgres -d filas_teste -c "GRANT DELETE ON saida TO processador;"

# O pg_hba.conf passou a aceitar o observador.
psql_como_postgres -d postgres -c "SELECT pg_reload_conf();" > /dev/null
echo "Papel observador criado; histórico operacional fora do papel painel."
