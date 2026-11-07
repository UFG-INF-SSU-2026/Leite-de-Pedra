#!/bin/sh
set -eu

senha() { tr -d '\n' < "/run/segredos/$1.password"; }

psql -v ON_ERROR_STOP=1 -U postgres -d postgres \
    -v senha_processador="$(senha processador)" \
    -v senha_backend="$(senha backend)" \
    -v senha_painel="$(senha painel)" \
    -v senha_observador="$(senha observador)" <<'SQL'
CREATE ROLE processador LOGIN PASSWORD :'senha_processador';
CREATE ROLE backend LOGIN PASSWORD :'senha_backend';
CREATE ROLE painel LOGIN PASSWORD :'senha_painel';
CREATE ROLE observador LOGIN PASSWORD :'senha_observador';
CREATE DATABASE filas_teste;
REVOKE ALL ON DATABASE filas, filas_teste FROM PUBLIC;
GRANT CONNECT ON DATABASE filas, filas_teste TO processador, backend, painel, observador;
SQL

for banco in filas filas_teste; do
    psql -v ON_ERROR_STOP=1 -U postgres -d "$banco" -f /esquema.sql
    psql -v ON_ERROR_STOP=1 -U postgres -d "$banco" -f /ingressos.sql
done

psql -v ON_ERROR_STOP=1 -U postgres -d filas_teste \
    -c "GRANT DELETE ON filas, movimentos, estados, saida TO processador;"
