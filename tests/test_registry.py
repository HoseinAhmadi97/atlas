import pytest

from atlas.registry import load_fetcher


def test_loads_example_fetcher():
    fetcher = load_fetcher(
        "atlas.fetchers.example_fetcher", "ExampleFetcher", isins=["A", "B"]
    )
    assert fetcher.name == "example"
    assert fetcher.config["isins"] == ["A", "B"]


def test_rejects_non_fetcher_class():
    with pytest.raises(TypeError):
        load_fetcher("atlas.config", "AtlasConfig")


@pytest.mark.asyncio
async def test_example_fetcher_returns_one_record_per_isin():
    fetcher = load_fetcher(
        "atlas.fetchers.example_fetcher", "ExampleFetcher", isins=["A", "B", "C"]
    )
    records = await fetcher.fetch()
    assert {r.isin for r in records} == {"A", "B", "C"}
