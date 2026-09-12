from __future__ import annotations

import asyncio
import datetime as dt
from zoneinfo import ZoneInfo

import jdatetime
import requests

from atlas.base import Fetcher, RawRecord

# Tadbir NAV feed for TSE gold funds -- public, no auth required.
#
# Reference: ~/TSE-GOLD-ALGO/datasources_fetchers/fetch_nav.py polls
# this same endpoint (plus a second, Farabi, provider that needs a
# real account's auth token -- not built here, see CLAUDE.md) and
# writes both into hist.gold_fund_nav, distinguished only by `source`.
# This fetcher covers the Tadbir half; `source` is "tadbir" to match
# that table's existing values exactly.

TADBIR_URL_TMPL = (
    "https://core.tadbirrlc.com//StockFutureInfoHandler"
    '?%7B%22Type%22:%22etf%22,%22la%22:%22fa%22,%22nscCode%22:%22{isin}%22%7D'
    "&jsoncallback="
)

TEHRAN_TZ = ZoneInfo("Asia/Tehran")

# Static gold-fund ISIN list, copied from TSE-GOLD-ALGO's utils/base.py
# (`gold_isin`) instead of read at runtime from market_fetcher's
# `all_tickers_info` Redis key -- that key can be stale (no TTL) or
# simply absent (market_fetcher isn't always running). Update this list
# by hand if utils/base.py's gold_isin changes.
DEFAULT_GOLD_ISINS = [
    "IRTKLOTF0001", "IRTKZARF0001", "IRTKKIAN0001", "IRTKMOFD0001",
    "IRTKROBA0001", "IRTKZARA0001", "IRTKZFAM0001", "IRTKNAFS0001",
    "IRTKGANJ0001", "IRTKNAAB0001", "IRTKALTN0001", "IRTKJAVA0001",
    "IRTKTABA0001", "IRTKLIAN0001", "IRTKZARV0001", "IRTKDRKS0001",
    "IRTKATSH0001", "IRTKGHIR0001", "IRTKGOLN0001", "IRTKZOMR0001",
    "IRTKEMRL0001", "IRTKROSE0001", "IRTKDORN0001", "IRTKZARG0001",
    "IRTKRITO0001", "IRTKROZG0001", "IRTKJAMF0001", "IRTKNGIN0001",
    "IRTKGOLD0001", "IRTKHAMY0001", "IRTKMIRA0001",
]


def _parse_nav_date(value: str | None) -> dt.datetime | None:
    """Parse Tadbir's Jalali "YYYY/M/D HH:MM" into an Asia/Tehran-aware datetime.

    Returns None on anything unparsable -- RawRecord.source_ts already
    falls back to `ts` when this is None.
    """
    if not value:
        return None
    try:
        date_part, time_part = value.split()
        y, m, d = (int(x) for x in date_part.split("/"))
        hh, mm = (int(x) for x in time_part.split(":"))
        return jdatetime.datetime(y, m, d, hh, mm).togregorian().replace(tzinfo=TEHRAN_TZ)
    except (ValueError, TypeError):
        return None


def _fetch_one(isin: str) -> dict:
    """Blocking HTTP call -- always run through an executor (see fetch()),
    never directly on the event loop: 31 of these run one poll."""
    resp = requests.get(TADBIR_URL_TMPL.format(isin=isin), timeout=10)
    resp.raise_for_status()
    return resp.json()["Value"][0]


class NavTadbirFetcher(Fetcher):
    """Tadbir NAV feed for TSE gold funds, one HTTP call per ISIN per poll."""

    name = "tadbir"

    async def fetch(self) -> list[RawRecord]:
        isins = self.config.get("isins", DEFAULT_GOLD_ISINS)
        now = dt.datetime.now(TEHRAN_TZ)

        loop = asyncio.get_event_loop()
        results = await asyncio.gather(
            *(loop.run_in_executor(None, _fetch_one, isin) for isin in isins),
            return_exceptions=True,
        )

        records = []
        for isin, result in zip(isins, results):
            if isinstance(result, Exception):
                continue
            nav = result.get("CancelNAV")
            if nav is None:
                continue
            records.append(
                RawRecord(
                    isin=isin,
                    ts=now,
                    price=nav,
                    payload=result,
                    source_ts=_parse_nav_date(result.get("NAVDate")),
                )
            )
        return records
