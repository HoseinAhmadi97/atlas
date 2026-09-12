from __future__ import annotations

import json
from typing import Iterable

import redis

from atlas.base import RawRecord

KEY_PREFIX = "atlas:raw"


class RedisSink:
    """Latest-value cache. One key per (datasource, symbol).

    Values carry a TTL so a datasource that stops fetching goes stale
    and disappears instead of serving a frozen snapshot forever -- the
    failure mode `market_fetcher`'s no-TTL `SET` has today.
    """

    def __init__(self, client: redis.Redis, default_ttl_s: int = 120) -> None:
        self.client = client
        self.default_ttl_s = default_ttl_s

    def key(self, datasource: str, symbol: str) -> str:
        return f"{KEY_PREFIX}:{datasource}:{symbol}"

    def write(
        self,
        datasource: str,
        records: Iterable[RawRecord],
        ttl_s: int | None = None,
    ) -> None:
        ttl = ttl_s if ttl_s is not None else self.default_ttl_s
        pipe = self.client.pipeline(transaction=False)
        for r in records:
            value = json.dumps(
                {
                    "ts": r.ts.isoformat(),
                    "symbol": r.symbol,
                    "source": r.source,
                    "payload": r.payload,
                },
                ensure_ascii=False,
                default=str,
            )
            pipe.set(self.key(datasource, r.symbol), value, ex=ttl)
        pipe.execute()

    def read(self, datasource: str, symbol: str) -> dict | None:
        raw = self.client.get(self.key(datasource, symbol))
        return json.loads(raw) if raw is not None else None
