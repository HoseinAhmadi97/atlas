from unittest.mock import patch

import pytest

from atlas.fetchers.tabdeal_fetcher import TITLE_TO_ISIN, TabdealFetcher

CURRENCY_RESPONSE = [
    {"price_title": "دلار", "last_price": "2339000", "price_change": -0.89},
    {"price_title": "یورو", "last_price": "2722800", "price_change": -0.91},
]
COIN_RESPONSE = [
    {"price_title": "سکه امامی", "last_price": "2395050000", "price_change": -0.63},
]
GOLD_RESPONSE = [
    {"price_title": "طلای ۱۸ عیار", "last_price": "238702000", "price_change": -1.3},
    {"price_title": "یک عیار ناشناخته", "last_price": "1", "price_change": 0},
]


def _fake_fetch_one(url):
    if "currency" in url:
        return CURRENCY_RESPONSE
    if "coin" in url:
        return COIN_RESPONSE
    if "gold" in url:
        return GOLD_RESPONSE
    raise AssertionError(f"unexpected url {url}")


@pytest.mark.asyncio
async def test_fetch_returns_one_record_per_known_row_across_all_three_endpoints():
    fetcher = TabdealFetcher()
    with patch("atlas.fetchers.tabdeal_fetcher._fetch_one", side_effect=_fake_fetch_one):
        records = await fetcher.fetch()

    # "یک عیار ناشناخته" has no TITLE_TO_ISIN entry -> skipped
    assert {r.isin for r in records} == {"dollar", "euro", "sekee_emami", "geram18"}


@pytest.mark.asyncio
async def test_price_is_the_raw_api_number_unconverted():
    # Regression: Tabdeal's last_price unit changed (Rial -> Toman)
    # without notice a day after this fetcher was first written, which
    # made a baked-in /10 conversion silently wrong. price must be the
    # raw number, no assumed factor -- see the module docstring.
    fetcher = TabdealFetcher()
    with patch("atlas.fetchers.tabdeal_fetcher._fetch_one", side_effect=_fake_fetch_one):
        records = await fetcher.fetch()

    dollar = next(r for r in records if r.isin == "dollar")
    assert dollar.price == 2339000.0


@pytest.mark.asyncio
async def test_payload_carries_asset_type_and_raw_fields():
    fetcher = TabdealFetcher()
    with patch("atlas.fetchers.tabdeal_fetcher._fetch_one", side_effect=_fake_fetch_one):
        records = await fetcher.fetch()

    dollar = next(r for r in records if r.isin == "dollar")
    assert dollar.payload["asset_type"] == "currency"
    assert dollar.payload["price_change"] == -0.89


@pytest.mark.asyncio
async def test_one_endpoint_failing_does_not_drop_the_others():
    def flaky_fetch_one(url):
        if "coin" in url:
            raise ConnectionError("boom")
        return _fake_fetch_one(url)

    fetcher = TabdealFetcher()
    with patch("atlas.fetchers.tabdeal_fetcher._fetch_one", side_effect=flaky_fetch_one):
        records = await fetcher.fetch()

    assert {r.isin for r in records} == {"dollar", "euro", "geram18"}


# Regression: "geram_abshodeh" (14 chars) exceeded atlas.raw_ticks.isin
# (varchar(12)) and failed the WHOLE poll's batch insert -- not just
# that one row -- when smoke-tested live on the server.
def test_all_isin_codes_fit_the_varchar12_column():
    too_long = {title: isin for title, isin in TITLE_TO_ISIN.items() if len(isin) > 12}
    assert too_long == {}


@pytest.mark.asyncio
async def test_unparsable_price_is_skipped():
    def fetch_one(url):
        if "currency" in url:
            return [{"price_title": "دلار", "last_price": "not-a-number"}]
        return []

    fetcher = TabdealFetcher()
    with patch("atlas.fetchers.tabdeal_fetcher._fetch_one", side_effect=fetch_one):
        records = await fetcher.fetch()

    assert records == []
