from unittest.mock import MagicMock, patch

import pytest

from atlas.fetchers.nav_farabi_fetcher import (
    NavFarabiFetcher,
    _parse_nav_date_of_event,
)

SAMPLE_FARABI_RESPONSE = {
    "isin": "IRTKZARF0001",
    "priceOfRedemptionNav": 1019483,
    "navDateOfEvent": "2026-09-12T17:55:33.554",
    "instrumentName": "Zar Gold Fund",
}


def test_parse_nav_date_of_event_handles_fractional_seconds():
    ts = _parse_nav_date_of_event("2026-09-12T17:55:33.554")
    assert ts is not None
    assert ts.tzinfo is not None
    assert (ts.year, ts.month, ts.day, ts.hour, ts.minute, ts.second) == (
        2026, 9, 12, 17, 55, 33,
    )


def test_parse_nav_date_of_event_handles_no_fractional_seconds():
    ts = _parse_nav_date_of_event("2026-09-12T17:55:33")
    assert ts.microsecond == 0


@pytest.mark.parametrize("bad", [None, "", "garbage"])
def test_parse_nav_date_of_event_returns_none_on_unparsable(bad):
    assert _parse_nav_date_of_event(bad) is None


@pytest.mark.asyncio
async def test_fetch_gets_token_once_and_reuses_it():
    fetcher = NavFarabiFetcher(isins=["IRTKZARF0001", "IRTKMOFD0001"])

    with patch("atlas.fetchers.nav_farabi_fetcher._fetch_token") as mock_token, patch(
        "atlas.fetchers.nav_farabi_fetcher.requests.get"
    ) as mock_get:
        mock_token.return_value = "Bearer abc123"
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: dict(SAMPLE_FARABI_RESPONSE),
            raise_for_status=lambda: None,
        )

        await fetcher.fetch()
        await fetcher.fetch()

    assert mock_token.call_count == 1  # cached across polls


@pytest.mark.asyncio
async def test_fetch_returns_one_record_per_isin_with_price_and_source_ts():
    fetcher = NavFarabiFetcher(isins=["IRTKZARF0001"])

    with patch("atlas.fetchers.nav_farabi_fetcher._fetch_token", return_value="Bearer x"), patch(
        "atlas.fetchers.nav_farabi_fetcher.requests.get"
    ) as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: dict(SAMPLE_FARABI_RESPONSE),
            raise_for_status=lambda: None,
        )
        records = await fetcher.fetch()

    assert len(records) == 1
    rec = records[0]
    assert rec.isin == "IRTKZARF0001"
    assert rec.price == 1019483
    assert rec.source_ts == _parse_nav_date_of_event("2026-09-12T17:55:33.554")
    assert rec.payload["instrumentName"] == "Zar Gold Fund"


@pytest.mark.asyncio
async def test_401_drops_token_and_skips_that_isin_without_crashing():
    fetcher = NavFarabiFetcher(isins=["IRTKZARF0001"])
    fetcher._token = "Bearer stale"

    with patch("atlas.fetchers.nav_farabi_fetcher.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=401)
        records = await fetcher.fetch()

    assert records == []
    assert fetcher._token is None  # forces a fresh token on the next poll


@pytest.mark.asyncio
async def test_fetch_skips_isin_with_no_price():
    fetcher = NavFarabiFetcher(isins=["IRTKZARF0001"])

    with patch("atlas.fetchers.nav_farabi_fetcher._fetch_token", return_value="Bearer x"), patch(
        "atlas.fetchers.nav_farabi_fetcher.requests.get"
    ) as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"isin": "IRTKZARF0001", "priceOfRedemptionNav": None},
            raise_for_status=lambda: None,
        )
        records = await fetcher.fetch()

    assert records == []
