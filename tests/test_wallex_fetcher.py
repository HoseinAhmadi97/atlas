from unittest.mock import MagicMock, patch

import pytest

from atlas.fetchers.wallex_fetcher import WallexFetcher

SAMPLE_RESPONSE = {
    "result": {
        "markets": [
            {"symbol": "USDTTMN", "price": "233509", "base_asset": "USDT"},
            {"symbol": "ETHTMN", "price": "591143947", "base_asset": "ETH"},
            {"symbol": "BADMARKET", "price": None, "base_asset": "X"},
        ]
    }
}


@pytest.mark.asyncio
async def test_fetch_defaults_to_usdttmn_only():
    fetcher = WallexFetcher()
    with patch("atlas.fetchers.wallex_fetcher.requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            json=lambda: SAMPLE_RESPONSE, raise_for_status=lambda: None
        )
        records = await fetcher.fetch()

    assert len(records) == 1
    rec = records[0]
    assert rec.isin == "USDTTMN"
    assert rec.price == 233509.0
    assert rec.payload["base_asset"] == "USDT"
    assert rec.ts.tzinfo is not None
    assert rec.source_ts is None  # no per-tick timestamp field in the API


@pytest.mark.asyncio
async def test_fetch_respects_configured_symbol_list():
    fetcher = WallexFetcher(symbols=["USDTTMN", "ETHTMN"])
    with patch("atlas.fetchers.wallex_fetcher.requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            json=lambda: SAMPLE_RESPONSE, raise_for_status=lambda: None
        )
        records = await fetcher.fetch()

    assert {r.isin for r in records} == {"USDTTMN", "ETHTMN"}


@pytest.mark.asyncio
async def test_fetch_skips_market_with_no_price():
    fetcher = WallexFetcher(symbols=["BADMARKET"])
    with patch("atlas.fetchers.wallex_fetcher.requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            json=lambda: SAMPLE_RESPONSE, raise_for_status=lambda: None
        )
        records = await fetcher.fetch()

    assert records == []


@pytest.mark.asyncio
async def test_fetch_returns_empty_when_symbol_not_present():
    fetcher = WallexFetcher(symbols=["NOPE"])
    with patch("atlas.fetchers.wallex_fetcher.requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            json=lambda: SAMPLE_RESPONSE, raise_for_status=lambda: None
        )
        records = await fetcher.fetch()

    assert records == []
