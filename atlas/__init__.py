"""Atlas: raw datasource ingestion layer for the whole server.

Pulls price / time-series data from many datasources and writes it,
unmodified, into two sinks:

- Redis   -- latest-value cache, keyed per (datasource, symbol)
- Postgres/TimescaleDB -- append-only raw history (raw_ticks)

Atlas does not clean, join, or resample data. That is a separate,
downstream project that reads from these sinks.
"""
