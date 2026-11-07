-- Usuários do app (com o rosto no Rekognition), ingressos, auditoria do
-- dashboard e permissões dos papéis backend e painel. Aplicado depois de
-- esquema.sql, em filas e em filas_teste (inicializar.sh e atualizar-banco.sh).

GRANT USAGE ON SCHEMA public TO backend, painel, observador;

CREATE TABLE usuarios (
    usuario_id TEXT        PRIMARY KEY,           -- ExternalImageId do rosto no Rekognition
    login      TEXT        NOT NULL UNIQUE,
    senha_hash TEXT        NOT NULL,              -- scrypt (senhas.py)
    nome       TEXT        NOT NULL,
    papel      TEXT        NOT NULL DEFAULT 'cliente'
               CHECK (papel IN ('cliente', 'validador', 'admin')),
    face_id    TEXT        NOT NULL UNIQUE,       -- FaceId no Rekognition; a foto não é guardada
    criado_em  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE ingressos (
    ingresso_id  TEXT        PRIMARY KEY,         -- vai no QR code do app
    usuario_id   TEXT        NOT NULL REFERENCES usuarios,
    emitido_em   TIMESTAMPTZ NOT NULL DEFAULT now(),
    usado_em     TIMESTAMPTZ,
    fila_entrada TEXT,
    leitura_id   TEXT        UNIQUE,              -- eventId da leitura que validou o ingresso
    validador_id TEXT        REFERENCES usuarios, -- quem liberou a entrada
    cancelado_em TIMESTAMPTZ,                     -- cancelado por um admin; não entra mais
    CHECK ((usado_em IS NULL) = (leitura_id IS NULL))
);
CREATE INDEX ingressos_do_usuario ON ingressos (usuario_id);

-- Tudo o que um admin muda ou abre de sensível (troca de papel, cancelamento,
-- foto de leitura) fica registrado aqui. Ninguém altera nem apaga.
CREATE TABLE auditoria (
    auditoria_id BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    momento      TIMESTAMPTZ NOT NULL DEFAULT now(),
    admin_id     TEXT        NOT NULL REFERENCES usuarios,
    acao         TEXT        NOT NULL CHECK (acao IN ('mudar-papel', 'cancelar-ingresso', 'ver-foto')),
    alvo         TEXT        NOT NULL,
    detalhe      TEXT
);

-- Por que uma leitura foi recusada: validador-nao-autorizado, rosto-nao-confere,
-- ingresso-inexistente, ingresso-cancelado, ingresso-ja-usado ou falha-reconhecimento.
ALTER TABLE movimentos ADD COLUMN IF NOT EXISTS motivo TEXT;
-- Na decisão de cada leitura: o ingresso apresentado e quem leu (auditoria do admin).
ALTER TABLE movimentos ADD COLUMN IF NOT EXISTS ingresso_id TEXT;
ALTER TABLE movimentos ADD COLUMN IF NOT EXISTS validador_id TEXT;
-- Do contrato das mensagens: a operação de ponta a ponta (correlation_id) e
-- quem publicou (source). Num banco existente, rode só estas duas linhas.
ALTER TABLE movimentos ADD COLUMN IF NOT EXISTS correlacao_id TEXT;
ALTER TABLE movimentos ADD COLUMN IF NOT EXISTS origem TEXT;

-- backend (rotas do app): cadastra clientes e emite ingressos novos. Não escolhe
-- o papel, não marca entrada, não cancela, não apaga.
GRANT SELECT ON usuarios, ingressos TO backend;
GRANT INSERT (usuario_id, login, senha_hash, nome, face_id) ON usuarios TO backend;
GRANT INSERT (ingresso_id, usuario_id) ON ingressos TO backend;

-- painel (rotas de gestão do dashboard de admin): usuários, ingressos e
-- auditoria, menos as senhas, e só escreve o que o admin gerencia: o papel, o
-- cancelamento e a própria auditoria. Em movimentos, só confere se a leitura
-- existe antes de abrir a foto. O histórico operacional é da observabilidade.
GRANT SELECT ON movimentos, ingressos, auditoria TO painel;
GRANT SELECT (usuario_id, login, nome, papel, face_id, criado_em) ON usuarios TO painel;
GRANT UPDATE (papel) ON usuarios TO painel;
GRANT UPDATE (cancelado_em) ON ingressos TO painel;
GRANT INSERT (admin_id, acao, alvo, detalhe) ON auditoria TO painel;

-- observador (observabilidade): só lê o que o processador grava das filas e das
-- leituras; nada de usuários, ingressos ou auditoria.
GRANT SELECT ON filas, movimentos, estados, movimentos_por_minuto, espera_por_minuto, saida
    TO observador;

-- processador: confere o papel e o dono do ingresso e marca a entrada; não vê
-- senhas nem nomes.
GRANT SELECT (usuario_id, papel) ON usuarios TO processador;
GRANT SELECT, UPDATE (usado_em, fila_entrada, leitura_id, validador_id) ON ingressos TO processador;

-- Só no banco de testes o processador prepara e limpa os próprios dados.
SELECT current_database() = 'filas_teste' AS banco_de_teste \gset
\if :banco_de_teste
GRANT INSERT, DELETE ON usuarios, ingressos, auditoria TO processador;
GRANT SELECT ON auditoria TO processador;
\endif
