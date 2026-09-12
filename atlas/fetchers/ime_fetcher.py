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
            if last_update:
                # Naive local time as returned by the API -- the server
                # (and this parse) both assume Asia/Tehran.
                ts = dt.datetime.fromisoformat(last_update).replace(tzinfo=TEHRAN_TZ)
            else:
                ts = now

            records.append(
                RawRecord(symbol=symbol, ts=ts, source=self.source, payload=contract)
            )
        return records
