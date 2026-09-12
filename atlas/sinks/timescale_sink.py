from __future__ import annotations

import json
from typing import Iterable

import psycopg2
import psycopg2.extras

from atlas.base import RawRecord

INSERT_SQL = """
INSERT INTO raw_ticks (ts, datasource, symbol, payload)
VALUES %s
"""


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

    def write(self, datasource: str, records: Iterable[RawRecord]) -> None:
        rows = [
            (r.ts, datasource, r.symbol, json.dumps(r.payload, ensure_ascii=False, default=str))
            for r in records
        ]
        if not rows:
            return
        conn = self._connection()
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(cur, INSERT_SQL, rows)
        conn.commit()

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
