from __future__ import annotations

import datetime as dt
import json
from typing import Iterable
from zoneinfo import ZoneInfo

import psycopg2
import psycopg2.extras

from atlas.base import RawRecord

TEHRAN_TZ = ZoneInfo("Asia/Tehran")

INSERT_SQL = """
INSERT INTO atlas.raw_ticks (isin, time, price, created_at, received_at, source, payload)
VALUES %s
ON CONFLICT (isin, time, source) DO NOTHING
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


class TimescaleSink:
    """Append-only raw history. One row per observation.

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
            time_ = _naive_tehran(r.ts)
            rows.append(
                (
                    r.isin,
                    time_,
                    r.price,
                    _naive_tehran(r.resolved_source_ts()),
                    time_,  # received_at: same wall-clock capture as `time`
                    source,
                    json.dumps(r.payload, ensure_ascii=False, default=str),
                )
            )
        if not rows:
            return
        conn = self._connection()
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, INSERT_SQL, rows)
        conn.commit()

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
