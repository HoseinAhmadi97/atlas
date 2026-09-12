# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this is

The raw ingestion layer for the `alpha` quant server: many datasources
(price/time-series, growing over time), one fetch loop each, writing
unmodified JSON into Redis (latest value) and Postgres/TimescaleDB
(`atlas.raw_ticks`, append-only). See `README.md` and `docs/architecture.md`.

**Atlas does not clean data.** A separate, later project reads
`atlas.raw_ticks` / the Redis keys and produces cleaned/joined data behind an
API. Do not add cleaning, resampling, or symbol-mapping logic here --
that decision was made explicitly when this repo was started (2026-09-12).

## Invariants

1. **Adding a datasource never touches `runner.py` or `registry.py`.**
   It is a new file in `atlas/fetchers/` plus an entry in
   `config/datasources.yaml`. If a change to add a datasource touches
   either of those two files, stop and reconsider the design. This
   holds regardless of extraction method -- a JSON API call and an HTML
   scrape (see `example_fetcher.py` vs `example_scrape_fetcher.py`) are
   both just a `fetch()` implementation; neither needs anything from the
   pipeline that the other doesn't already have.

2. **One datasource's failure must never affect another's.** `runner.py`
   runs one asyncio task per datasource with its own try/except around
   `fetch()` and around each sink write. Do not collapse these into a
   shared try/except across datasources.

3. **Redis and Postgres writes are independent, not transactional.**
   A Redis write succeeding while the Postgres write fails (or vice
   versa) is logged and accepted, not retried-as-a-pair. Don't add a
   distributed-transaction layer over this -- momentary disagreement
   between "latest value" and "history" is fine; blocking every
   datasource on both sinks succeeding is not.

4. **Redis keys always carry a TTL.** `market_fetcher.py` (a different,
   pre-existing project on this server) sets keys with no expiry, so a
   dead fetcher's last value is served forever with nothing to say it's
   stale. `RedisSink` defaults `ttl_s` from config specifically to avoid
   reproducing that here.

5. **`atlas/db/schema.sql`'s hypertable conversion is commented out, and
   `scripts/bootstrap_db.py` decides at runtime whether to apply it.**
   Postgres extensions are per-database -- checking `pg_extension` on
   the wrong database (e.g. `postgres` instead of `quant_db`) gives a
   false "not installed" reading, which is what happened once during
   this repo's setup. `quant_db` already has TimescaleDB (2.29.2,
   shared with TSE-GOLD-ALGO's own hypertables) and `atlas.raw_ticks`
   is a hypertable in it. If Atlas is ever pointed at a Postgres that
   truly lacks the extension, `bootstrap_db.py` must keep degrading to
   a plain indexed table rather than attempting an install or a
   `systemctl restart postgresql` itself -- that restart is a
   shared-service action affecting other projects on the box.

6. **All Atlas tables live in the `atlas` schema, never `public`.**
   `quant_db` (the database Atlas uses on the server) is TSE-GOLD-ALGO's
   live trading database, with its own `hist`/`live` schemas already in
   it. `atlas.raw_ticks` (schema-qualified) is the one table; a new
   datasource is a new row shape in that same table (via the
   `datasource` column), never a new table, and never anything created
   outside the `atlas` schema.

7. **The default DSN uses the Postgres Unix socket, not a password.**
   `postgresql://quant@/quant_db?host=/var/run/postgresql` peer-auths as
   OS user `quant` -- it works only because Atlas always runs as `quant`
   on the same box as Postgres. Don't swap this for a TCP host without
   checking pg_hba.conf allows it and a real password is available; the
   whole point was to avoid putting a DB password in `.env`.

8. **This repo does not modify or delete anything in the other project
   directories on the server** (`market_fetcher/`, `TSE-GOLD-ALGO/`,
   `alpha-capital/`). Their fetchers are consulted for conventions
   (Redis key patterns, `.env` naming, `.gitignore` shape) but migrating
   their logic into an Atlas fetcher is a separate, deliberate task per
   datasource -- not something to do incidentally while touching Atlas.

## Conventions

- `from __future__ import annotations` throughout, matching the other
  server-side repos' Python-3.10 target.
- Fetchers are `async def fetch()` even when the underlying HTTP call is
  sync-only for now -- keeps `runner.py`'s scheduling uniform as
  datasources with real async I/O are added.
- `payload` in `RawRecord` / `atlas.raw_ticks` is stored as opaque JSON. Do not
  add columns for datasource-specific fields to `atlas.raw_ticks` -- if a
  field needs to be queried directly and efficiently, that belongs in
  the downstream cleaned-data project's own schema, not here.
- Every `RawRecord` carries `source` (a URL or short label for exactly
  where the data physically came from) alongside `datasource` (the
  config/registry grouping key, e.g. `"ime"`). A `Fetcher` subclass
  declares a `source` class attribute and reuses it per record unless
  it genuinely reads from more than one endpoint. Don't conflate the
  two or drop `source` to save a column -- it is what makes provenance
  answerable from the data itself instead of from memory of which
  fetcher wrote it.

## Verifying changes

No live Redis/Postgres needed for the test suite:

```bash
python -m py_compile atlas/*.py atlas/**/*.py scripts/*.py
pytest
```

`scripts/bootstrap_db.py` and running `atlas/runner.py` for real do need
a reachable Postgres (`ATLAS_PG_DSN`) and Redis -- see README
"Prerequisites".
