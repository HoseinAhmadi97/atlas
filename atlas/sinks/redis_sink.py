from __future__ import annotations

import json
from typing import Iterable

import redis

from atlas.base import RawRecord

KEY_PREFIX = "atlas:raw"


class RedisSink:
    """Latest-value snapshot cache. One key per (source, isin), no TTL:
    a key is simply overwritten on the next successful write, never
    expired. A datasource that stops fetching leaves its last value in
    place rather than the key disappearing -- freshness is judged from
    `time`/`created_at` inside the value itself, not from whether the
    key still exists.
    """

    def __init__(self, client: redis.Redis) -> None:
        self.client = client

    def key(self, source: str, isin: str) -> str:
        return f"{KEY_PREFIX}:{source}:{isin}"

    def write(self, source: str, records: Iterable[RawRecord]) -> None:
        pipe = self.client.pipeline(transaction=False)
        for r in records:
            value = json.dumps(
                {
                    "time": r.ts.isoformat(),
                    "isin": r.isin,
                    "source": source,
                    "price": r.price,
                    "created_at": r.resolved_source_ts().isoformat(),
                    "payload": r.payload,
                },
                ensure_ascii=False,
                default=str,
            )
            pipe.set(self.key(source, r.isin), value)
        pipe.execute()

    def read(self, source: str, isin: str) -> dict | None:
        raw = self.client.get(self.key(source, isin))
        return json.loads(raw) if raw is not None else None
