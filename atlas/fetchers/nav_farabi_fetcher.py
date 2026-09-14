from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo

import requests

from atlas.base import Fetcher, RawRecord
from atlas.gold_isins import GOLD_ISINS

# Farabi NAV feed for TSE gold funds -- the second provider
# ~/TSE-GOLD-ALGO/datasources_fetchers/fetch_nav.py polls (Tadbir is
# the first, see nav_tadbir_fetcher.py), writing into the same
# hist.gold_fund_nav table with `source="farabi"`.
#
# Unlike Tadbir, this needs a real trading account's auth token --
# fetch_nav.py already depends on the same local `auto_farabi_fetch`
# service (account "Ahamdi_Farabi") for this, so this fetcher is a
# second, independent consumer of that same token, not a new
# capability. It never calls os._exit() the way fetch_nav.py does on a
# dead token: a token failure here just skips this poll's Farabi
# records and forces a fresh token on the next one (see fetch()) --
# killing the whole process would take every other datasource down
# with it, violating the one-datasource-failure-shouldn't-affect-
# others rule the rest of Atlas follows.

FARABI_AUTO_FETCH_URL = "http://127.0.0.1:8000/auto_farabi_fetch"
FARABI_STOCKWATCH_URL_TMPL = "https://gateway.farabixo.com/api/v2/stockwatch/{isin}/simple"
DEFAULT_ACCOUNT_NAME = "Ahamdi_Farabi"

TEHRAN_TZ = ZoneInfo("Asia/Tehran")


class _AuthError(Exception):
    """The cached Farabi token was rejected (401) for one request."""


def _fetch_token(account_name: str) -> str:
    """Blocking HTTP call -- run through an executor, see _ensure_token()."""
    resp = requests.get(
        FARABI_AUTO_FETCH_URL, params={"account_name": account_name}, timeout=(3, 30)
    )
    resp.raise_for_status()
    return "Bearer " + resp.json()["token"]


def _fetch_one(isin: str, token: str) -> dict:
    """Blocking HTTP call -- always run through an executor (see fetch()),
    never directly on the event loop: 31 of these run one poll."""
    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "fa,en-US;q=0.9,en;q=0.8",
        "authorization": token,
    }
    resp = requests.get(FARABI_STOCKWATCH_URL_TMPL.format(isin=isin), headers=headers, timeout=10)
    if resp.status_code == 401:
        raise _AuthError(f"Farabi token rejected for {isin}")
    resp.raise_for_status()
    return resp.json()


def _parse_nav_date_of_event(value: str | None) -> dt.datetime | None:
    """Parse Farabi's "YYYY-MM-DDTHH:MM:SS[.ffffff]" into an Asia/Tehran-aware
    datetime. Not `datetime.fromisoformat`: like IME's LastUpdate, the
    fractional-second digit count isn't guaranteed to be exactly 3 or 6
    (see ime_fetcher.py's _parse_last_update for the same issue).
    """
    if not value:
        return None
    fmt = "%Y-%m-%dT%H:%M:%S.%f" if "." in value else "%Y-%m-%dT%H:%M:%S"
    try:
        return dt.datetime.strptime(value, fmt).replace(tzinfo=TEHRAN_TZ)
    except ValueError:
        return None


def _correct_meridiem(source_ts: dt.datetime, now: dt.datetime) -> dt.datetime:
    """Undo a 12-hour-without-PM navDateOfEvent -- confirmed live on
    IRTKKIAN0001 (fund "گوهر") on 2026-09-14: every poll's navDateOfEvent
    came back exactly 12 hours behind the poll's own wall-clock time
    (e.g. reported 02:22:43 while every other Farabi fund and the fetch
    itself agreed on 14:23:00), while every other fund in the same batch
    was unaffected -- so this is Farabi mis-serializing one fund's field,
    not a systemic clock issue. Same fix as ime_fetcher.py's
    _correct_meridiem (see there for the general rationale): navDateOfEvent
    is always within seconds of the poll, so shifting by 12 hours only
    when that lands closer to `now` self-corrects without needing to
    hardcode which fund is affected.
    """
    if source_ts.hour >= 12:
        return source_ts
    shifted = source_ts.replace(hour=source_ts.hour + 12)
    return shifted if abs(now - shifted) < abs(now - source_ts) else source_ts


class NavFarabiFetcher(Fetcher):
    """Farabi NAV feed for TSE gold funds, one HTTP call per ISIN per poll."""

    name = "farabi"

    def __init__(self, **config: Any) -> None:
        super().__init__(**config)
        self._token: str | None = None

    async def _ensure_token(self) -> str:
        if self._token is None:
            account_name = self.config.get("account_name", DEFAULT_ACCOUNT_NAME)
            loop = asyncio.get_event_loop()
            self._token = await loop.run_in_executor(None, _fetch_token, account_name)
        return self._token

    async def fetch(self) -> list[RawRecord]:
        isins = self.config.get("isins", GOLD_ISINS)
        now = dt.datetime.now(TEHRAN_TZ)
        token = await self._ensure_token()

        loop = asyncio.get_event_loop()
        results = await asyncio.gather(
            *(loop.run_in_executor(None, _fetch_one, isin, token) for isin in isins),
            return_exceptions=True,
        )

        records = []
        saw_auth_error = False
        for isin, result in zip(isins, results):
            if isinstance(result, _AuthError):
                saw_auth_error = True
                continue
            if isinstance(result, Exception):
                continue
            price = result.get("priceOfRedemptionNav")
            if price is None:
                continue
            source_ts = _parse_nav_date_of_event(result.get("navDateOfEvent"))
            if source_ts is not None:
                source_ts = _correct_meridiem(source_ts, now)
            records.append(
                RawRecord(
                    isin=isin,
                    ts=now,
                    price=price,
                    payload=result,
                    source_ts=source_ts,
                )
            )

        if saw_auth_error:
            self._token = None  # force a fresh token on the next poll

        return records
