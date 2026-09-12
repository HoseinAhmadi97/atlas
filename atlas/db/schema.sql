-- Raw ingestion table, in its own schema so it never shares a
-- namespace with another project's tables in the same database (e.g.
-- TSE-GOLD-ALGO's `hist`/`live` schemas in quant_db).
--
-- Schema-on-read: `payload` holds the datasource's native shape as
-- JSON, unparsed. Cleaning/normalizing happens in a separate
-- downstream project, not here.

CREATE SCHEMA IF NOT EXISTS atlas;

CREATE TABLE IF NOT EXISTS atlas.raw_ticks (
    ts          timestamptz NOT NULL,
    datasource  text        NOT NULL,
    symbol      text        NOT NULL,
    payload     jsonb       NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS raw_ticks_ds_symbol_ts_idx
    ON atlas.raw_ticks (datasource, symbol, ts DESC);

-- Hypertable conversion requires the timescaledb extension to already
-- be installed at the OS/package level (this file cannot do that --
-- see README.md "Prerequisites"). Run once, manually, after confirming
-- `SELECT * FROM pg_extension WHERE extname = 'timescaledb';` returns a
-- row:
--
--   CREATE EXTENSION IF NOT EXISTS timescaledb;
--   SELECT create_hypertable('atlas.raw_ticks', 'ts', if_not_exists => TRUE);
--
-- Until then, atlas.raw_ticks works fine as a plain indexed table --
-- just without TimescaleDB's chunking/compression.
