import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

from atlas.fetchers.ime_fetcher import TEHRAN_TZ, IMEFetcher, _correct_meridiem, _parse_last_update

SAMPLE_RESPONSE = [
    {
        "ContractCode": "LeadIngot",
        "ContractDescription": "Lead Ingot Deposit Certificate",
        "LastUpdate": "2026-09-12T16:48:00.493",
        "LastTradedPrice": 4710000.0,
        "LastSettlementPrice": 4612976.0,
    },
    {
        "ContractCode": "ZincIngot",
        "LastUpdate": None,
        "LastTradedPrice": 1234.0,
    },
]


@pytest.mark.asyncio
async def test_parses_one_record_per_contract():
    fetcher = IMEFetcher()
    with patch("atlas.fetchers.ime_fetcher.requests.get") as mock_get:
        mock_get.return_value = MagicMock(json=lambda: SAMPLE_RESPONSE, raise_for_status=lambda: None)
        records = await fetcher.fetch()

    assert {r.isin for r in records} == {"LeadIngot", "ZincIngot"}
    lead = next(r for r in records if r.isin == "LeadIngot")
    assert lead.price == 4710000.0
    assert lead.payload["LastTradedPrice"] == 4710000.0
    assert lead.ts.tzinfo is not None


@pytest.mark.asyncio
async def test_ts_is_fetch_time_not_source_time():
    """`ts` must be the poll's wall-clock time, not LastUpdate -- that's
    what keeps (isin, time, source) collision-free when LastUpdate
    repeats across polls. `source_ts` carries the source's own value."""
    fetcher = IMEFetcher()
    with patch("atlas.fetchers.ime_fetcher.requests.get") as mock_get:
        mock_get.return_value = MagicMock(json=lambda: SAMPLE_RESPONSE, raise_for_status=lambda: None)
        records = await fetcher.fetch()

    lead = next(r for r in records if r.isin == "LeadIngot")
    assert lead.source_ts == _parse_last_update("2026-09-12T16:48:00.493")
    assert lead.ts != lead.source_ts


@pytest.mark.asyncio
async def test_missing_last_update_leaves_source_ts_none():
    fetcher = IMEFetcher()
    with patch("atlas.fetchers.ime_fetcher.requests.get") as mock_get:
        mock_get.return_value = MagicMock(json=lambda: SAMPLE_RESPONSE, raise_for_status=lambda: None)
        records = await fetcher.fetch()

    zinc = next(r for r in records if r.isin == "ZincIngot")
    assert zinc.source_ts is None
    assert zinc.resolved_source_ts() == zinc.ts  # falls back to ts


@pytest.mark.asyncio
async def test_skips_contracts_with_no_symbol():
    fetcher = IMEFetcher()
    bad_response = [{"LastUpdate": "2026-09-12T16:48:00.493"}]
    with patch("atlas.fetchers.ime_fetcher.requests.get") as mock_get:
        mock_get.return_value = MagicMock(json=lambda: bad_response, raise_for_status=lambda: None)
        records = await fetcher.fetch()

    assert records == []


# Regression: the real API trims trailing zeros from fractional
# seconds ("2026-09-12T16:53:35.08" was observed live), which
# datetime.fromisoformat rejects on Python <3.11.
@pytest.mark.parametrize(
    "raw, expected_microsecond",
    [
        ("2026-09-12T16:53:35.08", 80000),
        ("2026-09-12T16:53:35.493", 493000),
        ("2026-09-12T16:53:35", 0),
    ],
)
def test_parse_last_update_handles_trimmed_fractional_seconds(raw, expected_microsecond):
    ts = _parse_last_update(raw)
    assert ts.microsecond == expected_microsecond
    assert ts.tzinfo is not None


@pytest.mark.asyncio
async def test_fetch_handles_trimmed_fractional_seconds_from_api():
    fetcher = IMEFetcher()
    response = [{"ContractCode": "LeadIngot", "LastUpdate": "2026-09-12T16:53:35.08"}]
    with patch("atlas.fetchers.ime_fetcher.requests.get") as mock_get:
        mock_get.return_value = MagicMock(json=lambda: response, raise_for_status=lambda: None)
        records = await fetcher.fetch()

    assert records[0].source_ts == dt.datetime(
        2026, 9, 12, 16, 53, 35, 80000, tzinfo=records[0].source_ts.tzinfo
    )


# Regression: one IME contract has been observed reporting LastUpdate on
# a 12-hour clock with no PM marker -- 13:xx serialized as 01:xx. Message
# text from IME never flags this (unlike the TSE broker's closed-market
# strings elsewhere in this repo family), so the only signal is that the
# reported time is implausibly far from the poll that just fetched it.
@pytest.mark.parametrize(
    "source_hour, now_hour, expected_hour",
    [
        (1, 13, 13),   # 01:xx claimed, polled at 13:xx -- PM marker dropped, fix it
        (11, 23, 23),  # same bug at the far edge of the 12-hour range
        (13, 13, 13),  # already correct 24-hour -- leave alone
        (0, 0, 0),     # genuinely midnight and now is midnight -- no correction needed
        (3, 4, 3),     # plain few-minutes clock drift, not the AM/PM bug -- leave alone
    ],
)
def test_correct_meridiem(source_hour, now_hour, expected_hour):
    now = dt.datetime(2026, 9, 13, now_hour, 5, 0, tzinfo=TEHRAN_TZ)
    source_ts = dt.datetime(2026, 9, 13, source_hour, 4, 58, tzinfo=TEHRAN_TZ)
    assert _correct_meridiem(source_ts, now).hour == expected_hour


@pytest.mark.asyncio
async def test_fetch_corrects_pm_last_update_reported_without_marker():
    response = [{"ContractCode": "LeadIngot", "LastUpdate": "2026-09-13T01:59:58.0"}]
    fixed_now = dt.datetime(2026, 9, 13, 14, 0, 0, tzinfo=TEHRAN_TZ)

    class _FrozenDateTime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    fetcher = IMEFetcher()
    with patch("atlas.fetchers.ime_fetcher.requests.get") as mock_get, patch(
        "atlas.fetchers.ime_fetcher.dt.datetime", _FrozenDateTime
    ):
        mock_get.return_value = MagicMock(json=lambda: response, raise_for_status=lambda: None)
        records = await fetcher.fetch()

    assert records[0].source_ts.hour == 13
