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


class IMEFetcher(Fetcher):
    """IME CDC live market: one RawRecord per contract per poll."""

    name = "ime"
    source = "https://dataapi.ime.co.ir/api/CDC/CDCLiveMarket"

    async def fetch(self) -> list[RawRecord]:
        resp = requests.get(self.source, timeout=(3, 10))
        resp.raise_for_status()
        contracts = resp.json()

        now = dt.datetime.now(TEHRAN_TZ)
        records = []
        for contract in contracts:
            symbol = contract.get("ContractCode")
            if not symbol:
                continue  # can't key a record with no symbol

            last_update = contract.get("LastUpdate")
            ts = _parse_last_update(last_update) if last_update else now

            records.append(
                RawRecord(symbol=symbol, ts=ts, source=self.source, payload=contract)
            )
        return records
