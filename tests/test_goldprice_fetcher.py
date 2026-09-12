import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

from atlas.fetchers.goldprice_fetcher import GoldpriceFetcher

SAMPLE_RESPONSE = {
    "ts": 1789230254341,
    "tsj": 1789230245535,
    "date": "Sep 12th 2026, 12:24:05 pm NY",
    "items": [
        {
            "curr": "USD",
            "xauPrice": 4348.78,
            "xagPrice": 64.4934,
            "chgXau": -16.995,
            "chgXag": 0.1381,
        }
    ],
}


@pytest.mark.asyncio
async def test_fetch_returns_gold_and_silver_records():
    fetcher = GoldpriceFetcher()
    with patch("atlas.fetchers.goldprice_fetcher.requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            json=lambda: SAMPLE_RESPONSE, raise_for_status=lambda: None
        )
        records = await fetcher.fetch()

    assert {r.isin for r in records} == {"ons_tala", "ons_noghre"}
    gold = next(r for r in records if r.isin == "ons_tala")
    silver = next(r for r in records if r.isin == "ons_noghre")
    assert gold.price == 4348.78
    assert silver.price == 64.4934


@pytest.mark.asyncio
async def test_source_ts_matches_tsj_as_utc_epoch_millis():
    fetcher = GoldpriceFetcher()
    expected = dt.datetime.fromtimestamp(1789230245535 / 1000, tz=dt.timezone.utc)

    with patch("atlas.fetchers.goldprice_fetcher.requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            json=lambda: SAMPLE_RESPONSE, raise_for_status=lambda: None
        )
        records = await fetcher.fetch()

    for r in records:
        assert r.source_ts == expected  # same instant, regardless of tzinfo label


@pytest.mark.asyncio
async def test_fetch_sends_required_headers():
    fetcher = GoldpriceFetcher()
    with patch("atlas.fetchers.goldprice_fetcher.requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            json=lambda: SAMPLE_RESPONSE, raise_for_status=lambda: None
        )
        await fetcher.fetch()

    _args, kwargs = mock_get.call_args
    headers = kwargs["headers"]
    assert headers["origin"] == "https://goldprice.org"
    assert "user-agent" in headers


@pytest.mark.asyncio
async def test_payload_includes_full_item_and_envelope_fields():
    fetcher = GoldpriceFetcher()
    with patch("atlas.fetchers.goldprice_fetcher.requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            json=lambda: SAMPLE_RESPONSE, raise_for_status=lambda: None
        )
        records = await fetcher.fetch()

    payload = records[0].payload
    assert payload["chgXau"] == -16.995
    assert payload["date"] == "Sep 12th 2026, 12:24:05 pm NY"
