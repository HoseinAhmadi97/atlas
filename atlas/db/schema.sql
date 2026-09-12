-- Raw ingestion table, in its own schema so it never shares a
-- namespace with another project's tables in the same database (e.g.
-- TSE-GOLD-ALGO's `hist`/`live` schemas in quant_db).
--
-- Column names deliberately mirror hist.gold_fund_nav /
-- hist.gold_fundamental (nav -> price) instead of inventing a new
-- convention. See atlas/base.py's RawRecord docstring for the full
-- ts/time/created_at/received_at mapping and why they aren't all the
-- same value.
--
-- `payload` is the one addition beyond that convention: schema-on-read,
-- holds the datasource's native shape as JSON, unparsed. Cleaning/
-- normalizing happens in a separate downstream project, not here.

CREATE SCHEMA IF NOT EXISTS atlas;

CREATE TABLE IF NOT EXISTS atlas.raw_ticks (
    isin        varchar(12) NOT NULL,
    time        timestamp without time zone NOT NULL,
    price       numeric,
    created_at  timestamp without time zone NOT NULL,
    received_at timestamp without time zone NOT NULL,
    source      varchar(50) NOT NULL,
    payload     jsonb       NOT NULL,
    PRIMARY KEY (isin, time, source)
);

-- For "recent history from this source across all instruments" --
-- the PK alone only helps once `isin` is already known.
CREATE INDEX IF NOT EXISTS raw_ticks_source_time_idx
    ON atlas.raw_ticks (source, time DESC);

-- Hypertable conversion requires the timescaledb extension (already
-- enabled in quant_db as of 2026-09-12 -- see README.md
-- "Prerequisites"). Run once, manually, after confirming
-- `SELECT * FROM pg_extension WHERE extname = 'timescaledb';` returns a
-- row:
--
--   SELECT create_hypertable('atlas.raw_ticks', 'time', if_not_exists => TRUE);
--
-- Until then, atlas.raw_ticks works fine as a plain indexed table --
-- just without TimescaleDB's chunking/compression.
