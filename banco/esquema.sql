CREATE EXTENSION IF NOT EXISTS timescaledb;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO processador;

CREATE TABLE filas (
    fila_id  TEXT PRIMARY KEY,
    entradas INTEGER NOT NULL DEFAULT 0,
    saidas   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE movimentos (
    evento_id   TEXT        NOT NULL,
    fila_id     TEXT        NOT NULL,
    tipo        TEXT        NOT NULL CHECK (tipo IN ('contagem', 'saida', 'leitura', 'resultado')),
    momento     TIMESTAMPTZ NOT NULL,
    recebido_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    resultado   TEXT        CHECK (resultado IN ('aceito', 'recusado', 'indeterminado')),
    PRIMARY KEY (evento_id, tipo, momento)
);
SELECT create_hypertable('movimentos', by_range('momento'));

CREATE TABLE estados (
    momento          TIMESTAMPTZ NOT NULL DEFAULT now(),
    fila_id          TEXT        NOT NULL,
    semaforo         TEXT        NOT NULL CHECK (semaforo IN ('livre', 'atencao', 'bloqueada')),
    ocupacao         INTEGER     NOT NULL,
    espera_segundos  INTEGER
);
SELECT create_hypertable('estados', by_range('momento'));

CREATE MATERIALIZED VIEW movimentos_por_minuto
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket('1 minute', momento) AS minuto,
       fila_id,
       count(*) FILTER (WHERE tipo = 'contagem')            AS entradas,
       count(*) FILTER (WHERE tipo = 'saida')               AS saidas,
       count(*) FILTER (WHERE resultado = 'aceito')         AS aceitos,
       count(*) FILTER (WHERE resultado = 'recusado')       AS recusados,
       count(*) FILTER (WHERE resultado = 'indeterminado')  AS indeterminados
FROM movimentos
GROUP BY minuto, fila_id
WITH NO DATA;

CREATE MATERIALIZED VIEW espera_por_minuto
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket('1 minute', momento) AS minuto,
       fila_id,
       avg(espera_segundos)::INTEGER AS espera_media,
       max(espera_segundos)          AS espera_maxima,
       max(ocupacao)                 AS ocupacao_maxima
FROM estados
GROUP BY minuto, fila_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('movimentos_por_minuto',
    start_offset => INTERVAL '1 hour', end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute');
SELECT add_continuous_aggregate_policy('espera_por_minuto',
    start_offset => INTERVAL '1 hour', end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute');

-- Transactional outbox do processador: a publicação que depende de uma decisão
-- gravada (o resultado de uma leitura) entra aqui na mesma transação da
-- decisão, e o processador a publica até o broker confirmar (publicado_em).
CREATE TABLE saida (
    evento_id    TEXT        PRIMARY KEY,
    topico       TEXT        NOT NULL,
    conteudo     TEXT        NOT NULL,
    criado_em    TIMESTAMPTZ NOT NULL DEFAULT now(),
    publicado_em TIMESTAMPTZ
);
CREATE INDEX saida_pendente ON saida (criado_em) WHERE publicado_em IS NULL;

GRANT SELECT, INSERT, UPDATE ON filas TO processador;
GRANT SELECT, INSERT ON movimentos, estados TO processador;
GRANT SELECT, INSERT, UPDATE (publicado_em) ON saida TO processador;
