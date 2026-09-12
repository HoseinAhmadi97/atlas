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
|-- fetchers/
|   |-- example_fetcher.py         # template: JSON/API-style datasource
|   |-- example_scrape_fetcher.py  # template: HTML-scraping datasource
|   `-- ime_fetcher.py             # real: Iran Mercantile Exchange live market
|-- sinks/
|   |-- redis_sink.py     # latest-value cache, TTL per key
|   `-- timescale_sink.py # append-only raw history
`-- db/
    `-- schema.sql         # atlas.raw_ticks table + hypertable notes

config/datasources.yaml    # one entry per datasource, see below
scripts/bootstrap_db.py    # idempotent: creates atlas.raw_ticks (+ hypertable if available)
deploy/atlas.service        # optional systemd unit
docs/architecture.md
tests/
```

## Adding a new datasource

1. Copy `atlas/fetchers/example_fetcher.py` -> `atlas/fetchers/<name>_fetcher.py`,
   implement `fetch()`.
2. Add an entry to `config/datasources.yaml`.
3. Restart the runner.

`runner.py` and `registry.py` are generic and never need to change.

`fetch()` doesn't care how the data is obtained -- a JSON API, a REST
client, or scraping an HTML page with BeautifulSoup are all valid, and
different datasources can use different methods. See
`atlas/fetchers/example_scrape_fetcher.py` for the scraping template
(`atlas/fetchers/example_fetcher.py` is the plain/JSON one). Add whatever
extraction library a given datasource needs to `requirements.txt`.

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
