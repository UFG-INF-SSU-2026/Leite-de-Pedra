-- Logins recusados e acessos negados da API, mostrados na auditoria do painel.
-- Aplicado depois de ingressos.sql, em filas e em filas_teste (inicializar.sh,
-- num banco novo; adicionar-seguranca.sh, num existente). Idempotente.

CREATE TABLE IF NOT EXISTS eventos_seguranca (
    evento_seguranca_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    momento    TIMESTAMPTZ NOT NULL DEFAULT now(),
    tipo       TEXT NOT NULL CHECK (tipo IN
               ('login-recusado', 'login-bloqueado', 'nao-autenticado', 'acesso-negado')),
    login      TEXT,   -- o informado na tentativa de login; pode não existir
    usuario_id TEXT,   -- do token válido, num acesso negado
    endereco   TEXT NOT NULL,
    metodo     TEXT NOT NULL,
    rota       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS eventos_seguranca_momento ON eventos_seguranca (momento DESC);

-- Só o backend escreve, e não lê, altera nem apaga; o painel só lê.
GRANT INSERT (tipo, login, usuario_id, endereco, metodo, rota) ON eventos_seguranca TO backend;
GRANT SELECT ON eventos_seguranca TO painel;

-- Só no banco de testes o processador limpa e confere os dados.
SELECT current_database() = 'filas_teste' AS banco_de_teste \gset
\if :banco_de_teste
GRANT SELECT, DELETE ON eventos_seguranca TO processador;
\endif
