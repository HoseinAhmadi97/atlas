# Atlas

Raw datasource ingestion layer for the server: pulls price / time-series
data from many datasources (more are added over time) and writes it,
unmodified, into Redis (latest value) and Postgres/TimescaleDB (raw
history). See [`docs/architecture.md`](docs/architecture.md) for the
full picture and why cleaning/serving is deliberately a separate,
later project.

## Structure

```
atlas/
|-- base.py              # Fetcher ABC + RawRecord -- the only contract
|-- registry.py          # config entry -> running Fetcher instance
|-- config.py            # loads .env + config/datasources.yaml
|-- runner.py             # entrypoint: one task per enabled datasource
|-- gold_isins.py         # static ISIN list shared by nav_tadbir/nav_farabi
|-- schedule.py           # ScheduleConfig: when a datasource may fetch
|-- fetchers/
|   |-- example_fetcher.py         # template: JSON/API-style datasource
|   |-- example_scrape_fetcher.py  # template: HTML-scraping datasource
|   |-- ime_fetcher.py             # real: Iran Mercantile Exchange live market
|   |-- nav_tadbir_fetcher.py      # real: TSE gold fund NAV, Tadbir provider
|   |-- nav_farabi_fetcher.py      # real: TSE gold fund NAV, Farabi provider
|   |-- estjt_fetcher.py           # real: estjt.ir gold/coin retail prices (HTML scrape)
|   `-- wallex_fetcher.py          # real: Wallex crypto/currency markets
|-- sinks/
|   |-- redis_sink.py     # latest-value snapshot cache, no TTL
|   `-- timescale_sink.py # latest-value-per-minute history (UPSERT)
`-- db/
    `-- schema.sql         # atlas.raw_ticks table + hypertable notes

config/datasources.yaml    # one entry per datasource, see below
scripts/bootstrap_db.py    # idempotent: creates atlas.raw_ticks (+ hypertable if available)
deploy/atlas.service        # optional systemd unit
docs/architecture.md
tests/
```

## Adding a new datasource, step by step

`runner.py` and `registry.py` are generic and never need to change for
any of this -- if a step below has you editing either, something is off.

### 1. Pick a short name

This becomes the `source` column value in `atlas.raw_ticks` and the
Redis key prefix (`atlas:raw:<name>:<isin>`), e.g. `"ime"`, `"nav_tadbir"`.

### 2. Copy a template

Two live in `atlas/fetchers/`:

- **`example_fetcher.py`** -- JSON/API-style datasource (has a JSON
  endpoint to call). This is what `ime_fetcher.py` and
  `nav_tadbir_fetcher.py` are built from.
- **`example_scrape_fetcher.py`** -- HTML-scraping datasource (uses
  BeautifulSoup). `fetch()` doesn't care how the data is obtained;
  different datasources can use different methods, and a fetcher is
  free to add whatever extraction library it needs to
  `requirements.txt`.

```bash
cp atlas/fetchers/example_fetcher.py atlas/fetchers/<name>_fetcher.py
```

### 3. Write the fetcher class

In the new file:

1. Rename the class (e.g. `MyNewFetcher`).
2. Set `name = "<name>"` (from step 1).
3. Replace `fetch()`'s body with the real call. It must return a list
   of `RawRecord`:

```python
RawRecord(
    isin=...,        # instrument/symbol identifier
    ts=...,          # wall-clock time of THIS fetch -- not the source's own timestamp
    price=...,       # one scalar number, or None if there isn't one
    payload={...},   # the whole raw record, unparsed -- don't narrow it down
    source_ts=...,   # optional: the source's own reported timestamp, if it has one
)
```

**`ts` vs `source_ts` matters.** `ts` must always be the fetch's own
wall-clock moment, never something the source returned -- that's what
keeps `(isin, time, source)` collision-free even when the source's own
timestamp repeats across polls (see the schema section below). If the
source does report its own timestamp (IME's `LastUpdate`, Tadbir's
`NAVDate`), put it in `source_ts` so it still ends up in `created_at`.
See `atlas/fetchers/ime_fetcher.py` or `atlas/fetchers/nav_tadbir_fetcher.py`
for worked examples.

### 4. Register it in `config/datasources.yaml`

```yaml
  - name: my_new_source
    module: atlas.fetchers.my_new_source_fetcher
    class: MyNewFetcher
    interval_s: 10          # poll interval, in seconds
    enabled: false          # flip to true after step 6-7
    kwargs: {}              # any extra args fetch() needs (e.g. a symbol list)
    schedule:               # optional -- omit entirely for "always allowed"
      workdays_only: true
      start: "12:00"
      end: "18:00"
```

### 5. (Recommended) write a test

`tests/test_<name>_fetcher.py`, mocking `requests.get` (or whatever
`fetch()` calls) so it runs offline. See `tests/test_ime_fetcher.py` or
`tests/test_nav_tadbir_fetcher.py` for the pattern.

### 6. Run locally

```bash
python -m py_compile atlas/*.py atlas/**/*.py scripts/*.py
pytest -q
```

### 7. Smoke-test the fetcher alone, without touching the running service

```python
import asyncio
from atlas.fetchers.my_new_source_fetcher import MyNewFetcher

async def main():
    records = await MyNewFetcher().fetch()
    print(len(records))
    for r in records[:3]:
        print(r.isin, r.price, r.ts, r.source_ts)

asyncio.run(main())
```

### 8. Deploy

```bash
git add -A && git commit -m "..." && git push
```

On the server: `git pull --ff-only`, then repeat step 6 there.

### 9. Flip `enabled: true` and restart

```bash
sudo systemctl restart atlas.service
```

### 10. Verify it's actually flowing

```sql
SELECT * FROM atlas.raw_ticks WHERE source = 'my_new_source' ORDER BY time DESC LIMIT 5;
```

```bash
redis-cli KEYS "atlas:raw:my_new_source:*"
```

## When a datasource is allowed to fetch

An optional `schedule:` block per datasource in `config/datasources.yaml`
controls this -- checked in Asia/Tehran time before every poll:

```yaml
schedule:
  workdays_only: true   # Iran work week (Saturday-Wednesday) only
  start: "12:00"         # inclusive
  end: "18:00"           # inclusive
```

Outside the window, `runner.py` just sleeps and rechecks -- `fetch()`
is never called and nothing is written to either sink, so a closed
market doesn't cost so much as one HTTP request. Omit `schedule:`
entirely for "always allowed" (what `example`/`example_scrape` do).
`ime`, `tadbir`, and `farabi` all currently use the same window above.

## atlas.raw_ticks schema

Columns deliberately mirror `hist.gold_fund_nav` / `hist.gold_fundamental`
(`nav` renamed `price`) instead of inventing a new convention:

| Column        | Type                        | Meaning |
|---------------|-----------------------------|---------|
| `isin`        | `varchar(12)`               | Instrument identifier. Not always a literal ISIN (e.g. IME's `"LeadIngot"`) -- kept as the name to match the server's existing tables. |
| `time`        | `timestamp without time zone` | Wall-clock time Atlas fetched this record, **truncated to the minute**. Not the source's own timestamp -- see below. |
| `price`       | `numeric`, nullable          | One scalar price, if the datasource has one. |
| `created_at`  | `timestamp without time zone` | The source's own reported timestamp (e.g. IME's `LastUpdate`), full precision. |
| `received_at` | `timestamp without time zone` | The same fetch moment as `time`, but at **full precision** (not truncated) -- when this row was last actually written. |
| `source`      | `varchar(50)`                | Short label for which datasource wrote this row (the `Fetcher.name`, e.g. `"ime"`). |
| `payload`     | `jsonb`                      | The full raw record, unparsed -- the one column beyond the mirrored convention. |

Primary key: `(isin, time, source)`.

**`atlas.raw_ticks` is latest-value-per-minute, not a full tick log.**
This mirrors `utils/db.py`'s `AsyncDataBuffer` in TSE-GOLD-ALGO exactly:
`add_data()` truncates `time` to the minute floor and upserts on
`(isin, time, source)`. A poll that lands in a minute already written
for that `(isin, source)` **updates** `price`/`created_at`/
`received_at`/`payload` in place rather than adding a row -- so IME
polling every 2 seconds still produces at most one row per instrument
per minute, refreshed each poll, not sixty near-duplicate rows.
`created_at` and `received_at` both stay at full precision so "when did
the source last report this" and "when did we last see it" survive the
truncation even though `time` itself doesn't. In `RawRecord`
(`atlas/base.py`) this is `ts` (-> `time`/`received_at`) and `source_ts`
(-> `created_at`, defaults to `ts` when a datasource has no independent
timestamp). See `TimescaleSink` in `atlas/sinks/timescale_sink.py` for
the UPSERT itself.

## Prerequisites (server)

- Postgres reachable at `ATLAS_PG_DSN`. On the `alpha` quant box, Atlas
  uses the existing `quant_db` database (Postgres 16, already running)
  but its own `atlas` schema -- `quant_db` also holds TSE-GOLD-ALGO's
  live `hist`/`live` schemas, and `atlas.raw_ticks` is deliberately kept
  out of that namespace. The socket-based DSN in `.env.example` needs no
  password: it peer-auths as OS user `quant` over the local Unix socket,
  which only works because Atlas always runs as `quant` on this same box.
- **TimescaleDB extension** is already enabled in `quant_db` (2.29.2,
  same one TSE-GOLD-ALGO's own hypertables use -- extensions are
  per-database, and an earlier check of the `postgres` database showing
  only `plpgsql` was a false negative). `scripts/bootstrap_db.py`
  detected it and converted `atlas.raw_ticks` to a hypertable
  automatically; nothing further to install. If Atlas is ever pointed
  at a *different* Postgres that genuinely lacks the extension,
  `bootstrap_db.py` still degrades gracefully to a plain indexed table
  and says so -- it never attempts an install or a restart itself.
- The `quant` role needs `CREATE` on whichever database Atlas's schema
  lives in (`GRANT CREATE ON DATABASE <db> TO quant;`, run once by
  whoever owns Postgres) -- `quant_db` didn't have this by default since
  `quant` only owned objects inside `hist`/`live`, not the database
  itself.
- Redis (already running on the box, already used by `market_fetcher`).
- Python: use the existing `/opt/quant/envs/quant/bin/python` (3.10,
  already has pandas/redis/psycopg2/sqlalchemy) -- no new env needed,
  just `pip install -r requirements.txt` into it, or create a venv.

## Quickstart

```bash
cp .env.example .env               # fill in ATLAS_PG_DSN
pip install -r requirements.txt
python scripts/bootstrap_db.py     # creates atlas.raw_ticks
# flip `enabled: true` on the `example` datasource in
# config/datasources.yaml, then:
python -m atlas.runner
```

```bash
pytest                              # unit tests, no real Redis/Postgres needed
```

## Relationship to existing fetchers

`market_fetcher` and `TSE-GOLD-ALGO/datasources_fetchers` (fetch_ime,
fetch_nav, fetch_gold_market_info) keep running as-is, untouched --
`atlas/fetchers/ime_fetcher.py` is a new, independent read of the same
public IME endpoint `fetch_ime.py` uses, not a replacement of it.
`fetch_ime.py` narrows each contract down to the 4 fields one downstream
table needs; the Atlas fetcher keeps the whole raw record as `payload`
(that narrowing is a cleaning decision for the future API/clean-data
project to make, not this layer's job). New datasources go into Atlas
from the start; the old ones migrate in gradually, each as its own
Atlas fetcher, when
there's time -- not as a single rewrite.

Same story for `fetch_nav.py`: both providers it polls are now covered.
`atlas/fetchers/nav_tadbir_fetcher.py` (`source="tadbir"`) reads the
same public, no-auth Tadbir endpoint. `atlas/fetchers/nav_farabi_fetcher.py`
(`source="farabi"`) reads the same Farabi endpoint, fetching its own
token from the same local `auto_farabi_fetch` service `fetch_nav.py`
already depends on -- a second, independent consumer of that token, by
deliberate decision, not something added in passing. Unlike
`fetch_nav.py`, it never kills the process on a dead token (`os._exit(1)`
there would take every other Atlas datasource down with it): a 401
just drops the cached token and skips that poll's Farabi records, and
the next poll fetches a fresh one.
