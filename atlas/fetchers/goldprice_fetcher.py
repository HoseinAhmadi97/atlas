from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import requests

from atlas.base import Fetcher, RawRecord

# goldprice.org international gold/silver spot price feed -- public,
# but gated on request headers: a bare User-Agent isn't enough (403),
# it also needs Origin/Referer matching a real browser hit from
# goldprice.org itself (verified live before writing this).
#
# Reference: user-supplied script hits the same endpoint for the same
# two prices. Atlas keeps the whole raw `items[0]` record as `payload`
# (change/close fields too) instead of narrowing to just the price.

GOLDPRICE_URL = "https://data-asg.goldprice.org/dbXRates/USD"

_HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9,fa;q=0.8,de;q=0.7",
    "origin": "https://goldprice.org",
    "referer": "https://goldprice.org/",
    "user-agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    ),
}

TEHRAN_TZ = ZoneInfo("Asia/Tehran")

# isin -> field in the API's items[0]
SYMBOL_FIELDS = {
    "ons_tala": "xauPrice",
    "ons_noghre": "xagPrice",
}


class GoldpriceFetcher(Fetcher):
    """goldprice.org gold (XAU) / silver (XAG) spot prices, USD/oz."""

    name = "goldprice"

    async def fetch(self) -> list[RawRecord]:
        resp = requests.get(GOLDPRICE_URL, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        item = data["items"][0]

        now = dt.datetime.now(TEHRAN_TZ)
        # "tsj" is milliseconds since epoch (UTC) -- the source's own
        # reported update time, not the fetch time.
        source_ts = dt.datetime.fromtimestamp(data["tsj"] / 1000, tz=TEHRAN_TZ)
        payload = {**item, "date": data.get("date"), "ts": data.get("ts"), "tsj": data.get("tsj")}

        records = []
        for isin, field in SYMBOL_FIELDS.items():
            price = item.get(field)
            if price is None:
                continue
            records.append(
                RawRecord(isin=isin, ts=now, price=float(price), payload=payload, source_ts=source_ts)
            )
        return records
