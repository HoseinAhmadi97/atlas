import pytest

from atlas.registry import load_fetcher


@pytest.mark.asyncio
async def test_offline_demo_parses_two_rows():
    fetcher = load_fetcher("atlas.fetchers.example_scrape_fetcher", "ExampleScrapeFetcher")
    records = await fetcher.fetch()

    by_isin = {r.isin: r.price for r in records}
    assert by_isin == {"DEMO1": 150.25, "DEMO2": 98.10}
