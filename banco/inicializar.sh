#!/bin/sh
set -eu

senha() { tr -d '\n' < "/run/segredos/$1.password"; }

psql -v ON_ERROR_STOP=1 -U postgres -d postgres \
    -v senha_processador="$(senha processador)" \
    -v senha_observador="$(senha observador)" <<'SQL'
CREATE ROLE processador LOGIN PASSWORD :'senha_processador';
CREATE ROLE observador LOGIN PASSWORD :'senha_observador';
CREATE DATABASE filas_teste;
REVOKE ALL ON DATABASE filas, filas_teste FROM PUBLIC;
GRANT CONNECT ON DATABASE filas, filas_teste TO processador, observador;
SQL

for banco in filas filas_teste; do
    psql -v ON_ERROR_STOP=1 -U postgres -d "$banco" -f /esquema.sql
done

psql -v ON_ERROR_STOP=1 -U postgres -d filas_teste \
    -c "GRANT TRUNCATE ON filas, movimentos, estados TO processador;"
