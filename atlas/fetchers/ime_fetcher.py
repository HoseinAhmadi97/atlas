from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import requests

from atlas.base import Fetcher, RawRecord

# Iran Mercantile Exchange (IME) live market feed -- one row per traded
# contract (metals, petrochemicals, etc.), no auth required.
#
# Reference: ~/TSE-GOLD-ALGO/datasources_fetchers/fetch_ime.py on the
# server hits the same endpoint and keeps only 4 of its ~60 fields for
# one specific downstream table. Atlas keeps the whole raw record as
# `payload` instead -- narrowing to a few fields is a cleaning decision,
# which belongs in the downstream project, not here.

IME_API_URL = "https://dataapi.ime.co.ir/api/CDC/CDCLiveMarket"

TEHRAN_TZ = ZoneInfo("Asia/Tehran")


def _parse_last_update(value: str) -> dt.datetime:
    """Parse IME's naive local timestamp into an Asia/Tehran-aware one.

    Not `datetime.fromisoformat`: the API trims trailing zeros from the
    fractional seconds (e.g. ".08" instead of ".080"), which
    `fromisoformat` rejects on Python <3.11 (it demands exactly 3 or 6
    digits). `strptime`'s `%f` accepts 1-6 digits and zero-pads on the
    right, which matches what a trimmed ".08" actually means (0.08s,
    not 0.008s).
    """
    fmt = "%Y-%m-%dT%H:%M:%S.%f" if "." in value else "%Y-%m-%dT%H:%M:%S"
    return dt.datetime.strptime(value, fmt).replace(tzinfo=TEHRAN_TZ)


def _correct_meridiem(source_ts: dt.datetime, now: dt.datetime) -> dt.datetime:
    """Undo IME's occasional 12-hour-without-PM LastUpdate (seen live on
    one contract: 13:xx rendered as 01:xx -- the "%H" field is documented
    but some contracts' backend evidently formats with "hh" instead).

    LastUpdate is always within a few seconds of the poll that fetched
    it, so the fix is comparative rather than a fixed cutoff: an hour
    below 12 is only rewritten to hour+12 when doing so lands closer to
    `now` than leaving it alone does. A genuine morning timestamp (there
    is none here -- IME's schedule starts at 12:00 -- but this keeps the
    function correct without hardcoding that) is left untouched because
    +12 would only move it further from `now`.
    """
    if source_ts.hour >= 12:
        return source_ts
    shifted = source_ts.replace(hour=source_ts.hour + 12)
    return shifted if abs(now - shifted) < abs(now - source_ts) else source_ts


class IMEFetcher(Fetcher):
    """IME CDC live market: one RawRecord per contract per poll."""

    name = "ime"

    async def fetch(self) -> list[RawRecord]:
        resp = requests.get(IME_API_URL, timeout=(3, 10))
        resp.raise_for_status()
        contracts = resp.json()

        # Wall-clock fetch time, not the source's own timestamp -- this
        # is `ts`, which is what keeps (isin, time, source) unique even
        # when IME's LastUpdate repeats across polls (see base.py).
        now = dt.datetime.now(TEHRAN_TZ)

        records = []
        for contract in contracts:
            isin = contract.get("ContractCode")
            if not isin:
                continue  # can't key a record with no identifier

            last_update = contract.get("LastUpdate")
            source_ts = _parse_last_update(last_update) if last_update else None
            if source_ts is not None:
                source_ts = _correct_meridiem(source_ts, now)

            records.append(
                RawRecord(
                    isin=isin,
                    ts=now,
                    price=contract.get("LastTradedPrice"),
                    payload=contract,
                    source_ts=source_ts,
                )
            )
        return records
