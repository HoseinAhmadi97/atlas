# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this is

The raw ingestion layer for the `alpha` quant server: many datasources
(price/time-series, growing over time), one fetch loop each, writing
unmodified JSON into Redis (latest value) and Postgres/TimescaleDB
(`raw_ticks`, append-only). See `README.md` and `docs/architecture.md`.

**Atlas does not clean data.** A separate, later project reads
`raw_ticks` / the Redis keys and produces cleaned/joined data behind an
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

5. **`atlas/db/schema.sql`'s hypertable conversion is commented out on
   purpose.** The TimescaleDB extension was not installed on the
   server's Postgres as of 2026-09-12 (only `plpgsql` was present), and
   installing it needs `apt install` + `systemctl restart postgresql`
   as root -- a shared-service restart that affects other projects on
   the box. `scripts/bootstrap_db.py` detects the extension's absence
   and skips the hypertable step with a message; it must never attempt
   the apt install or the restart itself.

6. **This repo does not modify or delete anything in the other project
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
- `payload` in `RawRecord` / `raw_ticks` is stored as opaque JSON. Do not
  add columns for datasource-specific fields to `raw_ticks` -- if a
  field needs to be queried directly and efficiently, that belongs in
  the downstream cleaned-data project's own schema, not here.

## Verifying changes

No live Redis/Postgres needed for the test suite:

```bash
python -m py_compile atlas/*.py atlas/**/*.py scripts/*.py
pytest
```

`scripts/bootstrap_db.py` and running `atlas/runner.py` for real do need
a reachable Postgres (`ATLAS_PG_DSN`) and Redis -- see README
"Prerequisites".
