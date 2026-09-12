from __future__ import annotations

import asyncio
import datetime as dt
from zoneinfo import ZoneInfo

import requests

from atlas.base import Fetcher, RawRecord

# Tabdeal festival asset-prices feed -- public, no auth. Three separate
# endpoints (currency/coin/gold), each a flat list of
# {"price_title": <Persian name>, "last_price": <Rial string>,
# "price_change": <percent>}.
#
# Reference: the user-supplied script expected a Nuxt-style payload
# with integer references to resolve (resolve_payload/
# find_price_objects) and kept only one target row per endpoint.
# Verified live before writing this: the actual response is already a
# plain flat list -- no reference resolution needed -- and each
# endpoint returns several rows in the one HTTP call the source script
# already pays for. Atlas keeps all of them instead of narrowing to
# the single row the script tracked.

URLS = {
    "currency": "https://api-web.tabdeal.org/r/festival/get-asset-prices/?asset_type=currency",
    "coin": "https://api-web.tabdeal.org/r/festival/get-asset-prices/?asset_type=coin",
    "gold": "https://api-web.tabdeal.org/r/festival/get-asset-prices/?asset_type=gold",
}

# Persian price_title -> short isin-like code, covering every row each
# endpoint currently returns. A title with no entry here is skipped
# (see fetch()) rather than sent as-is: a long Persian phrase would
# overflow atlas.raw_ticks.isin (varchar(12)) and fail the whole
# batch's insert, not just that one row. Update this map if Tabdeal
# adds a new asset.
TITLE_TO_ISIN = {
    "دلار": "dollar",
    "یورو": "euro",
    "پوند": "pound",
    "درهم": "dirham",
    "سکه بهار آزادی": "sekee_azadi",
    "سکه امامی": "sekee_emami",
    "نیم سکه": "nim",
    "ربع سکه": "rob",
    "سکه گرمی": "gerami",
    "طلای آبشده": "geram_abshodeh",
    "طلای ۱۸ عیار": "geram18",
    "طلای ۲۴ عیار": "geram24",
}

TEHRAN_TZ = ZoneInfo("Asia/Tehran")


def _fetch_one(url: str) -> list[dict]:
    """Blocking HTTP call -- run through an executor (see fetch()),
    never directly on the event loop: 3 of these run one poll."""
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    resp.raise_for_status()
    return resp.json()


class TabdealFetcher(Fetcher):
    """Tabdeal festival prices (currency/coin/gold). Prices convert
    Rial -> Toman (/10), matching every other Iranian datasource here."""

    name = "tabdeal"

    async def fetch(self) -> list[RawRecord]:
        loop = asyncio.get_event_loop()
        results = await asyncio.gather(
            *(loop.run_in_executor(None, _fetch_one, url) for url in URLS.values()),
            return_exceptions=True,
        )

        now = dt.datetime.now(TEHRAN_TZ)
        records = []
        for asset_type, result in zip(URLS, results):
            if isinstance(result, Exception):
                continue
            for item in result:
                title = item.get("price_title")
                isin = TITLE_TO_ISIN.get(title)
                if isin is None:
                    continue
                last_price = item.get("last_price")
                if last_price is None:
                    continue
                try:
                    price_rial = float(str(last_price).replace(",", ""))
                except ValueError:
                    continue
                records.append(
                    RawRecord(
                        isin=isin,
                        ts=now,
                        price=price_rial / 10,  # Rial -> Toman
                        payload={**item, "asset_type": asset_type},
                    )
                )
        return records
