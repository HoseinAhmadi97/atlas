# CLAUDE.md

Guidance for Claude Code working in this repository.

## What this is

The raw ingestion layer for the `alpha` quant server: many datasources
(price/time-series, growing over time), one fetch loop each, writing
unmodified JSON into Redis (latest value) and Postgres/TimescaleDB
(`atlas.raw_ticks`, latest-value-per-minute -- see invariant 9). See
`README.md` and `docs/architecture.md`.

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

4. **Redis keys never expire, by deliberate decision (2026-09-12).**
   `RedisSink` used to set a TTL specifically to avoid `market_fetcher.py`'s
   no-TTL keys serving a dead fetcher's stale value forever with nothing
   to say so. That tradeoff was reversed on purpose: Redis is
   latest-snapshot-only now, plain `SET` with no `ex=`, and freshness is
   judged from `time`/`created_at` inside the value itself, not from
   whether the key still exists. Do not reintroduce a TTL without that
   decision being revisited explicitly -- it isn't an oversight.

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
   datasource is a new row shape in that same table (via the `source`
   column), never a new table, and never anything created outside the
   `atlas` schema.

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

9. **`atlas.raw_ticks`'s typed columns (`isin`, `time`, `price`,
   `created_at`, `received_at`, `source`) deliberately mirror
   `hist.gold_fund_nav` / `hist.gold_fundamental` (`nav` renamed
   `price`), decided 2026-09-12 -- not this repo's own invention, don't
   rename them to something that reads better in isolation. `payload`
   (jsonb, full raw record) is the one addition beyond that convention.
   The mirroring goes deeper than column names: `TimescaleSink` truncates
   `time` to the minute floor and UPSERTs on `(isin, time, source)`,
   exactly like TSE-GOLD-ALGO's `utils/db.py` `AsyncDataBuffer.add_data()`
   -- so `atlas.raw_ticks` is latest-value-per-minute, not a full tick
   log. A second poll within the same minute updates the row (price,
   created_at, received_at, payload) instead of adding one. `received_at`
   is the same fetch moment as `time` but kept at full precision (not
   truncated) -- do not truncate it too, that's the one place a poll's
   exact wall-clock time survives. `RawRecord.ts` maps to
   `time`/`received_at`, `RawRecord.source_ts` maps to `created_at`
   (defaults to `ts`). Do not switch `ON CONFLICT ... DO UPDATE` back to
   `DO NOTHING` -- that was tried first and is wrong: it would silently
   drop every poll after the first one in a given minute instead of
   refreshing the row.

10. **`TimescaleSink` closes its connection on any write failure.** A
    failed INSERT leaves a psycopg2 connection in an aborted-transaction
    state; without an explicit `rollback()` + `close()`, every write
    after the first failure would silently keep failing forever (the
    connection is reused, never reconnected) until the whole process
    restarted -- found while this ran continuously against real IME
    traffic. Don't drop this handling to simplify `write()`.

11. **`nav_farabi_fetcher.py` must never kill the process on a dead
    token.** `fetch_nav.py`'s Farabi path calls `os._exit(1)` when its
    token is rejected -- fine for a single-purpose script, fatal here:
    it would take every other Atlas datasource down with it, violating
    invariant 2. `NavFarabiFetcher` instead drops its cached token
    (`self._token = None`) on a 401 and re-fetches on the next poll;
    that poll's Farabi records are simply skipped, same as any other
    per-isin failure. Do not "fix" this by reintroducing a hard exit,
    and do not add per-request retry-with-refresh either -- a stampede
    of ~31 concurrent token refreshes (one per ISIN) on every 401 is
    worse than losing one poll's data.

12. **A datasource's `schedule:` (in `config/datasources.yaml`) gates
    `fetch()` itself, not just what happens to its output.** `runner.py`
    checks `ds.schedule.allows(now_tehran())` before calling `fetch()`;
    outside the window it just sleeps and rechecks -- no fetch() call,
    no sink writes, no wasted HTTP requests to a source that's closed
    anyway. Don't move the check to run *after* `fetch()` (e.g. to
    filter results) -- the point is to not fetch at all outside the
    window. `ScheduleConfig` (`atlas/schedule.py`) has no dependency on
    `runner.py` or any fetcher, so it's cheap to unit-test in isolation
    (see `tests/test_schedule.py`) -- keep it that way rather than
    inlining the day/time logic into `runner.py`.

13. **Every `isin` a fetcher produces must fit `varchar(12)`, or the
    whole poll's batch insert fails -- not just that one row.**
    `TimescaleSink.write()` builds one `execute_values()` statement per
    poll; a single oversized value (`"geram_abshodeh"`, 14 chars,
    found live when `tabdeal_fetcher.py` was first smoke-tested) fails
    the entire INSERT and drops every other record from that poll too.
    A fetcher with a name -> isin map (`TITLE_TO_ISIN`,
    `SYMBOL_MAP`, ...) should have a test asserting every value is
    <=12 chars (see `test_all_isin_codes_fit_the_varchar12_column` in
    `tests/test_tabdeal_fetcher.py`), and an unmapped/unexpected name
    should be skipped, never sent through as-is or silently truncated.

14. **Any SQL against `atlas.raw_ticks` from outside Atlas (Grafana,
    an ad hoc psql session, a future consumer) must wrap
    `time`/`received_at`/`created_at` in `AT TIME ZONE 'Asia/Tehran'`
    before comparing against `now()` or a `timestamptz`.** Those
    columns are naive Tehran local time, not UTC -- Postgres treats a
    bare naive value as being in the connecting session's timezone
    (UTC for Grafana's datasource), so skipping the conversion silently
    shifts every timestamp by -03:30 without erroring. See
    `scripts/deploy_grafana_dashboard.py`'s panel SQL for the pattern,
    and README.md "Grafana" for how it was verified (staleness came
    out as single-digit seconds for live sources, not ~12600).

15. **Never bake an assumed unit-conversion factor into a fetcher for a
    source that doesn't document its own units.** `tabdeal_fetcher.py`
    originally divided `last_price` by 10 (Rial -> Toman); one day
    later Tabdeal's endpoints started returning Toman directly with no
    announcement, and the fixed /10 silently became a second,
    incorrect conversion -- caught by comparing against wallex's
    USDTTMN, which the unconverted raw number matched and the
    converted one didn't. `price` is the raw API number now; if a
    downstream consumer needs a consistent unit across pollers whose
    convention can drift, that decision belongs there (it can
    cross-check against a stable reference per poll), not as a
    constant baked into raw ingestion. This is also why `payload` is
    never narrowed: the full raw record is what lets a problem like
    this be diagnosed after the fact instead of just observed.

## Conventions

- `from __future__ import annotations` throughout, matching the other
  server-side repos' Python-3.10 target.
- Fetchers are `async def fetch()` even when the underlying HTTP call is
  sync-only for now -- keeps `runner.py`'s scheduling uniform as
  datasources with real async I/O are added.
- `payload` in `RawRecord` / `atlas.raw_ticks` is stored as opaque JSON,
  beyond the standard typed columns (see invariant 9). Do not add more
  columns for datasource-specific fields -- if a field needs to be
  queried directly and efficiently, that belongs in the downstream
  cleaned-data project's own schema, not here.
- `Fetcher.name` (e.g. `"ime"`) is the one identifier a datasource
  needs: it's the Redis key prefix, the registry/config key, and the
  `source` column value, all at once. Don't reintroduce a second,
  separate "where did this come from" field (a URL, an endpoint) as a
  top-level `RawRecord` attribute -- a fetcher that genuinely has its
  own endpoint constant keeps it as a private module-level constant
  (see `IME_API_URL` in `ime_fetcher.py`), not part of the Fetcher/
  RawRecord contract.

## Verifying changes

No live Redis/Postgres needed for the test suite:

```bash
python -m py_compile atlas/*.py atlas/**/*.py scripts/*.py
pytest
```

`scripts/bootstrap_db.py` and running `atlas/runner.py` for real do need
a reachable Postgres (`ATLAS_PG_DSN`) and Redis -- see README
"Prerequisites".
