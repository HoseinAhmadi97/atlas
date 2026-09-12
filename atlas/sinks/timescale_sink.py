from __future__ import annotations

import datetime as dt
import json
from typing import Iterable
from zoneinfo import ZoneInfo

import psycopg2
import psycopg2.extras

from atlas.base import RawRecord

TEHRAN_TZ = ZoneInfo("Asia/Tehran")

# UPSERT, not append-only: mirrors utils/db.py's AsyncDataBuffer, which
# truncates `time` to the minute and upserts on (isin, time, source) --
# so this is "latest value per instrument per minute", not a full tick
# log. See TimescaleSink's docstring for why.
INSERT_SQL = """
INSERT INTO atlas.raw_ticks (isin, time, price, created_at, received_at, source, payload)
VALUES %s
ON CONFLICT (isin, time, source) DO UPDATE SET
    price = EXCLUDED.price,
    created_at = EXCLUDED.created_at,
    received_at = EXCLUDED.received_at,
    payload = EXCLUDED.payload
"""


def _naive_tehran(ts: dt.datetime) -> dt.datetime:
    """atlas.raw_ticks stores naive local time, matching hist.gold_fund_nav.

    A tz-aware datetime is converted to Asia/Tehran wall-clock and its
    tzinfo dropped; an already-naive one is assumed to be Tehran local
    time as-is (e.g. a fetcher that parsed a naive source timestamp).
    """
    if ts.tzinfo is None:
        return ts
    return ts.astimezone(TEHRAN_TZ).replace(tzinfo=None)


def _minute_floor(ts: dt.datetime) -> dt.datetime:
    return ts.replace(second=0, microsecond=0)


class TimescaleSink:
    """Latest-value-per-minute history: one row per (isin, minute, source).

    Matches TSE-GOLD-ALGO's utils/db.py AsyncDataBuffer exactly: `time`
    is the fetch's wall-clock minute (truncated), `received_at` is that
    same wall-clock moment at full precision (not truncated), and a
    poll that lands in an already-seen minute UPDATEs the row instead
    of adding a new one -- the second and third poll in one minute
    don't triple the row count, they just refresh price/created_at/
    received_at/payload to the latest observation.

    Works against a plain Postgres table too -- the hypertable
    conversion (`db/schema.sql`) is what makes it a TimescaleDB sink,
    but this class doesn't care either way.
    """

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._conn: psycopg2.extensions.connection | None = None

    def _connection(self) -> psycopg2.extensions.connection:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.dsn)
        return self._conn

    def write(self, source: str, records: Iterable[RawRecord]) -> None:
        rows = []
        for r in records:
            received_at = _naive_tehran(r.ts)
            rows.append(
                (
                    r.isin,
                    _minute_floor(received_at),
                    r.price,
                    _naive_tehran(r.resolved_source_ts()),
                    received_at,
                    source,
                    json.dumps(r.payload, ensure_ascii=False, default=str),
                )
            )
        if not rows:
            return
        conn = self._connection()
        try:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(cur, INSERT_SQL, rows)
            conn.commit()
        except Exception:
            # A failed statement leaves the connection in an aborted
            # transaction; every write after this one would silently
            # fail forever otherwise. Closing forces _connection() to
            # reconnect fresh on the next call. rollback() can itself
            # fail if the connection is already broken (not just the
            # transaction) -- that's fine, close() below covers it.
            try:
                conn.rollback()
            except Exception:
                pass
            self.close()
            raise

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
