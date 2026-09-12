import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

from atlas.fetchers.ime_fetcher import IMEFetcher, _parse_last_update

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

    assert {r.symbol for r in records} == {"LeadIngot", "ZincIngot"}
    lead = next(r for r in records if r.symbol == "LeadIngot")
    assert lead.source == IMEFetcher.source
    assert lead.payload["LastTradedPrice"] == 4710000.0
    assert lead.ts.tzinfo is not None


@pytest.mark.asyncio
async def test_missing_last_update_falls_back_to_now():
    fetcher = IMEFetcher()
    with patch("atlas.fetchers.ime_fetcher.requests.get") as mock_get:
        mock_get.return_value = MagicMock(json=lambda: SAMPLE_RESPONSE, raise_for_status=lambda: None)
        records = await fetcher.fetch()

    zinc = next(r for r in records if r.symbol == "ZincIngot")
    assert zinc.ts is not None


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

    assert records[0].ts == dt.datetime(
        2026, 9, 12, 16, 53, 35, 80000, tzinfo=records[0].ts.tzinfo
    )
