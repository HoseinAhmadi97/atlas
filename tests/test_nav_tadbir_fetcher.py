import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

from atlas.fetchers.nav_tadbir_fetcher import NavTadbirFetcher, _parse_nav_date

SAMPLE_TADBIR_RESPONSE = {
    "CancelNAV": 1020621.0,
    "IssuanceNAV": 1025163.0,
    "NAVDate": "1405/6/21 17:49",
}


def test_parse_nav_date_converts_jalali_to_gregorian():
    ts = _parse_nav_date("1405/6/21 17:49")
    assert ts is not None
    assert ts.tzinfo is not None
    # 1405/06/21 Jalali -> 2026-09-12 Gregorian
    assert (ts.year, ts.month, ts.day, ts.hour, ts.minute) == (2026, 9, 12, 17, 49)


@pytest.mark.parametrize("bad", [None, "", "not a date", "1405/6/21"])
def test_parse_nav_date_returns_none_on_unparsable_input(bad):
    assert _parse_nav_date(bad) is None


@pytest.mark.asyncio
async def test_fetch_returns_one_record_per_isin():
    fetcher = NavTadbirFetcher(isins=["IRTKZARF0001", "IRTKMOFD0001"])

    def fake_get(url, timeout=10):
        return MagicMock(
            json=lambda: {"Value": [dict(SAMPLE_TADBIR_RESPONSE)]},
            raise_for_status=lambda: None,
        )

    with patch("atlas.fetchers.nav_tadbir_fetcher.requests.get", side_effect=fake_get):
        records = await fetcher.fetch()

    assert {r.isin for r in records} == {"IRTKZARF0001", "IRTKMOFD0001"}
    rec = records[0]
    assert rec.price == 1020621.0
    assert rec.source_ts == _parse_nav_date("1405/6/21 17:49")
    assert rec.ts.tzinfo is not None


@pytest.mark.asyncio
async def test_fetch_skips_isin_whose_request_raises():
    fetcher = NavTadbirFetcher(isins=["GOOD0000001", "BAD00000001"])

    def fake_get(url, timeout=10):
        if "BAD00000001" in url:
            raise ConnectionError("boom")
        return MagicMock(
            json=lambda: {"Value": [dict(SAMPLE_TADBIR_RESPONSE)]},
            raise_for_status=lambda: None,
        )

    with patch("atlas.fetchers.nav_tadbir_fetcher.requests.get", side_effect=fake_get):
        records = await fetcher.fetch()

    assert {r.isin for r in records} == {"GOOD0000001"}


@pytest.mark.asyncio
async def test_fetch_skips_isin_with_no_cancel_nav():
    fetcher = NavTadbirFetcher(isins=["NONAV000001"])

    with patch("atlas.fetchers.nav_tadbir_fetcher.requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            json=lambda: {"Value": [{"CancelNAV": None, "NAVDate": "1405/6/21 17:49"}]},
            raise_for_status=lambda: None,
        )
        records = await fetcher.fetch()

    assert records == []
