-- Raw ingestion table. Schema-on-read: `payload` holds the datasource's
-- native shape as JSON, unparsed. Cleaning/normalizing happens in a
-- separate downstream project, not here.

CREATE TABLE IF NOT EXISTS raw_ticks (
    ts          timestamptz NOT NULL,
    datasource  text        NOT NULL,
    symbol      text        NOT NULL,
    payload     jsonb       NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS raw_ticks_ds_symbol_ts_idx
    ON raw_ticks (datasource, symbol, ts DESC);

-- Hypertable conversion requires the timescaledb extension to already
-- be installed at the OS/package level (this file cannot do that --
-- see README.md "Prerequisites"). Run once, manually, after confirming
-- `SELECT * FROM pg_extension WHERE extname = 'timescaledb';` returns a
-- row:
--
--   CREATE EXTENSION IF NOT EXISTS timescaledb;
--   SELECT create_hypertable('raw_ticks', 'ts', if_not_exists => TRUE);
--
-- Until then, raw_ticks works fine as a plain indexed table -- just
-- without TimescaleDB's chunking/compression.
