import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

from atlas.fetchers.nav_farabi_fetcher import (
    TEHRAN_TZ,
    NavFarabiFetcher,
    _correct_meridiem,
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


# Regression: IRTKKIAN0001 ("گوهر") confirmed live on 2026-09-14 --
# navDateOfEvent came back exactly 12 hours behind the poll's own
# wall-clock time (02:22:43 reported while the fetch itself and every
# other fund agreed on 14:23:00), fund-specific, not a feed-wide issue.
@pytest.mark.parametrize(
    "source_hour, now_hour, expected_hour",
    [
        (2, 14, 14),   # the exact IRTKKIAN0001 case observed live
        (1, 13, 13),
        (13, 13, 13),  # already correct 24-hour -- leave alone
        (3, 4, 3),     # plain few-minutes drift, not the AM/PM bug -- leave alone
    ],
)
def test_correct_meridiem(source_hour, now_hour, expected_hour):
    now = dt.datetime(2026, 9, 14, now_hour, 23, 0, tzinfo=TEHRAN_TZ)
    source_ts = dt.datetime(2026, 9, 14, source_hour, 22, 43, tzinfo=TEHRAN_TZ)
    assert _correct_meridiem(source_ts, now).hour == expected_hour


@pytest.mark.asyncio
async def test_fetch_corrects_one_funds_nav_date_without_affecting_others():
    responses = {
        "IRTKKIAN0001": {
            "isin": "IRTKKIAN0001",
            "priceOfRedemptionNav": 500000,
            "navDateOfEvent": "2026-09-14T02:22:43",
        },
        "IRTKZARF0001": dict(SAMPLE_FARABI_RESPONSE, navDateOfEvent="2026-09-14T14:23:00"),
    }
    fixed_now = dt.datetime(2026, 9, 14, 14, 23, 0, tzinfo=TEHRAN_TZ)

    class _FrozenDateTime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    fetcher = NavFarabiFetcher(isins=["IRTKKIAN0001", "IRTKZARF0001"])

    def fake_get(url, headers=None, timeout=None):
        isin = url.rsplit("/", 2)[-2]
        return MagicMock(status_code=200, json=lambda: responses[isin], raise_for_status=lambda: None)

    with patch("atlas.fetchers.nav_farabi_fetcher._fetch_token", return_value="Bearer x"), patch(
        "atlas.fetchers.nav_farabi_fetcher.requests.get", side_effect=fake_get
    ), patch("atlas.fetchers.nav_farabi_fetcher.dt.datetime", _FrozenDateTime):
        records = await fetcher.fetch()

    kian = next(r for r in records if r.isin == "IRTKKIAN0001")
    zarf = next(r for r in records if r.isin == "IRTKZARF0001")
    assert kian.source_ts.hour == 14  # corrected from the reported 02
    assert zarf.source_ts.hour == 14  # already correct, untouched
