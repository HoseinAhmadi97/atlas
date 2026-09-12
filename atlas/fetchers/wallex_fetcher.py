from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import requests

from atlas.base import Fetcher, RawRecord

# Wallex markets feed -- public, no auth required.
#
# Reference: user-supplied script fetches this same endpoint for one
# symbol (USDTTMN) and keeps only symbol/price/fetch-time. Atlas keeps
# the whole raw market record as `payload` instead (many more fields:
# 24h change/volume, fair-price bands, OTC limits, ...) and defaults to
# the same one symbol, configurable via `kwargs.symbols`.

WALLEX_MARKETS_URL = "https://api.wallex.ir/hector/web/v1/markets"
DEFAULT_SYMBOLS = ["USDTTMN"]

TEHRAN_TZ = ZoneInfo("Asia/Tehran")


class WallexFetcher(Fetcher):
    """Wallex market prices, one HTTP call per poll covering every symbol."""

    name = "wallex"

    async def fetch(self) -> list[RawRecord]:
        symbols = set(self.config.get("symbols", DEFAULT_SYMBOLS))

        resp = requests.get(WALLEX_MARKETS_URL, timeout=10)
        resp.raise_for_status()
        markets = resp.json()["result"]["markets"]

        now = dt.datetime.now(TEHRAN_TZ)
        records = []
        for market in markets:
            symbol = market.get("symbol")
            if symbol not in symbols:
                continue
            price_raw = market.get("price")
            if price_raw is None:
                continue
            records.append(
                RawRecord(isin=symbol, ts=now, price=float(price_raw), payload=market)
            )
        return records
