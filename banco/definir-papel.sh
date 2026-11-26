#!/usr/bin/env bash
# Define o papel (cliente, validador ou admin) de um usuário já cadastrado pelo
# app. Serve para criar o primeiro admin; depois, os admins trocam papéis pelo
# dashboard. Roda como superusuário dentro do contêiner, que não aceita esse
# usuário pela rede.
set -euo pipefail

if [[ "$#" -ne 2 || ! "$1" =~ ^[a-z0-9_.-]{3,32}$ || ! "$2" =~ ^(cliente|validador|admin)$ ]]; then
    echo "Uso: $0 <login> cliente|validador|admin" >&2
    exit 1
fi

alterados=$(docker exec -i -u postgres leite-de-pedra-banco psql -v ON_ERROR_STOP=1 -d filas -tA \
    -v login="$1" -v papel="$2" <<'SQL'
WITH alterado AS (
    UPDATE usuarios SET papel = :'papel' WHERE login = :'login' RETURNING 1
) SELECT count(*) FROM alterado;
SQL
)
if [[ "$alterados" != "1" ]]; then
    echo "Usuário $1 não encontrado." >&2
    exit 1
fi
echo "$1 agora é $2. Ele precisa entrar de novo no app."
