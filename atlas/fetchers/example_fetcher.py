from __future__ import annotations

import datetime as dt
import random

from atlas.base import Fetcher, RawRecord

# Copy this file as a starting point for a real datasource:
#   1. rename the class and `name`
#   2. replace `fetch()` with the real HTTP/API call
#   3. add an entry in config/datasources.yaml pointing at it
# Nothing else in Atlas needs to change.


class ExampleFetcher(Fetcher):
    """Deterministic, offline demo fetcher -- no network calls.

    Exists to exercise the full pipeline (runner -> sinks) in dev and
    in tests without depending on any real broker/API credentials.
    """

    name = "example"

    async def fetch(self) -> list[RawRecord]:
        symbols = self.config.get("symbols", ["DEMO1", "DEMO2"])
        now = dt.datetime.now(dt.timezone.utc)
        return [
            RawRecord(symbol=s, ts=now, payload={"price": round(random.uniform(100, 200), 2)})
            for s in symbols
        ]
