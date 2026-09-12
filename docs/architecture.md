# Architecture

```
config/datasources.yaml
        |
        v
atlas/registry.py  --loads-->  atlas/fetchers/<name>_fetcher.py (subclass of Fetcher)
        |
        v
atlas/runner.py  -- one asyncio task per enabled datasource, own interval,
        |            own try/except so one datasource's failure never
        |            touches another's
        v
  RawRecord list
        |
        +----------------------+
        v                      v
 RedisSink                TimescaleSink
 (latest value,           (latest-value-per-minute,
  no TTL)                   atlas.raw_ticks table)
```

## Why this split

Atlas is the **raw** layer only: whatever a datasource returns goes into
Redis and Postgres unmodified, as JSON. No cleaning, joining, resampling,
or symbol-mapping happens here -- that is a separate, later project that
reads from these two sinks and serves clean data (an API layer, per the
plan discussed when this repo was started).

Keeping raw ingestion separate from cleaning means:

- a new datasource can go live the moment its fetcher is written --
  it doesn't need to wait for anyone to define what "clean" means for it
- a bug in the cleaning logic can never corrupt the raw history, since
  cleaning never writes back into `atlas.raw_ticks`
- multiple different cleaning/serving projects can read the same raw
  data without coordinating with each other

## Adding a datasource

1. Copy `atlas/fetchers/example_fetcher.py` to `atlas/fetchers/<name>_fetcher.py`.
2. Implement `fetch()` -- return a list of
   `RawRecord(isin, ts, price, payload, source_ts=None)`. `payload` can
   be any JSON-serializable dict; it is stored as-is. `ts` is the poll's
   own wall-clock time (not the source's timestamp -- see
   `README.md`'s schema table for why); pass `source_ts` only if the
   datasource reports its own timestamp and you want it preserved in
   `created_at`.
3. Add an entry to `config/datasources.yaml` pointing at the new module
   and class.
4. Restart the runner (or, in dev, just re-run `python -m atlas.runner`).

`atlas/runner.py` and `atlas/registry.py` never need to change for a new
datasource -- if you find yourself editing either, something is off.

### The extraction method is the fetcher's business, not the pipeline's

`Fetcher.fetch()` has exactly one contract: return `list[RawRecord]`.
How it gets there is not constrained -- a JSON API call, a paginated
REST client, or scraping an HTML page with BeautifulSoup are all equally
valid, and can be mixed freely across datasources. See
`atlas/fetchers/example_scrape_fetcher.py` for the scraping variant of
the template. A fetcher is free to depend on whatever library it needs
(`requests`, `bs4`, `lxml`, a vendor SDK, ...); `runner.py` and
`registry.py` only ever see the `Fetcher`/`RawRecord` contract, never the
extraction method behind it.

## Why Redis + Postgres, not just one

- Redis answers "what's the latest value for X right now" in
  microseconds, for anything on the server that wants the current price
  without touching Postgres.
- Postgres/TimescaleDB is where "what did X look like over the last N
  days" is answered from -- Redis holds one overwritten snapshot per
  key (no TTL, no history) and is never the place to reconstruct the
  past from.

They are written independently and are allowed to disagree briefly (e.g.
Redis write succeeds, Postgres write fails) -- `runner.py` logs each sink
failure separately rather than treating the pair as one transaction,
because losing one datasource's history for a few seconds is a much
smaller problem than one flaky sink blocking every other datasource.
