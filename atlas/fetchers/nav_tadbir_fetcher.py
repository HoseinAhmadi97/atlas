from __future__ import annotations

import asyncio
import datetime as dt
from zoneinfo import ZoneInfo

import jdatetime
import requests

from atlas.base import Fetcher, RawRecord
from atlas.gold_isins import GOLD_ISINS

# Tadbir NAV feed for TSE gold funds -- public, no auth required.
#
# Reference: ~/TSE-GOLD-ALGO/datasources_fetchers/fetch_nav.py polls
# this same endpoint (plus a second, Farabi, provider -- see
# nav_farabi_fetcher.py) and writes both into hist.gold_fund_nav,
# distinguished only by `source`. This fetcher covers the Tadbir half;
# `source` is "tadbir" to match that table's existing values exactly.

TADBIR_URL_TMPL = (
    "https://core.tadbirrlc.com//StockFutureInfoHandler"
    '?%7B%22Type%22:%22etf%22,%22la%22:%22fa%22,%22nscCode%22:%22{isin}%22%7D'
    "&jsoncallback="
)

TEHRAN_TZ = ZoneInfo("Asia/Tehran")


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
        isins = self.config.get("isins", GOLD_ISINS)
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
