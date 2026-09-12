from unittest.mock import MagicMock, patch

import pytest

from atlas.fetchers.estjt_fetcher import (
    EstjtFetcher,
    _clean_number,
    _parse_last_update,
)

# Real update-line format, straight from a live smoke test against
# estjt.ir: "Last update: 21 Shahrivar 1405 - 17:04:54" in Persian.
# The month name and digits must be the genuine Persian text -- the
# parser matches against _JALALI_MONTHS' Persian keys, there's no
# Latin equivalent to substitute for that specific piece.
REAL_UPDATE_TEXT = "آخرین بروزرسانی: ۲۱ شهریور ۱۴۰۵ - ۱۷:۰۴:۵۴"

# Prices as the real site actually renders them: Persian digits with
# U+066B as the thousands separator (not a decimal point) -- see
# test_clean_number_handles_persian_digits_and_thousands_separator.
# Row *labels* are ASCII placeholders since those are matched via the
# patched SYMBOL_MAP/WANTED below, not against the real Persian text.
SAMPLE_HTML = f"""
<html><body>
<div class="instant-price instant-price-gold">
  <table>
    <tr><td class="name">GOLD_OUNCE</td><td class="price">$ ۴۳۴۸</td></tr>
    <tr><td class="name">TEHRAN_QUOTE</td><td class="price">۱۰۴٫۲۶۰٫۰۰۰</td></tr>
    <tr><td class="name">GOLD_18K</td><td class="price">۲۴٫۰۶۸٫۶۰۰</td></tr>
  </table>
  <p class="text-center">{REAL_UPDATE_TEXT}</p>
</div>
<div class="instant-price instant-price-coin">
  <table>
    <tr><td class="name">NEW_COIN</td><td class="price">۲۳۹٫۰۰۰٫۰۰۰</td></tr>
  </table>
  <p class="text-center">{REAL_UPDATE_TEXT}</p>
</div>
</body></html>
"""


def _patch_symbol_maps():
    """estjt_fetcher's SYMBOL_MAP/WANTED are keyed by real Persian
    labels; tests use ASCII placeholders instead, so patch the module's
    maps to match rather than embedding Persian labels in HTML fixtures
    that don't need to test the Persian text itself."""
    symbol_map = {
        "GOLD_OUNCE": "ons_tala",
        "TEHRAN_QUOTE": "mazaneh_tehran",
        "GOLD_18K": "geram18",
        "NEW_COIN": "sekee_new",
    }
    wanted = frozenset(symbol_map) - {"TEHRAN_QUOTE"}
    return symbol_map, wanted


def test_clean_number_handles_persian_digits_and_thousands_separator():
    assert _clean_number("۲۴٫۱۴۷٫۱۰۰") == 24147100.0


def test_clean_number_handles_dollar_prefix():
    assert _clean_number("$ ۴۳۴۸") == 4348.0


def test_clean_number_returns_none_on_empty():
    assert _clean_number("") is None


def test_parse_last_update_converts_jalali_to_gregorian():
    ts = _parse_last_update(REAL_UPDATE_TEXT)
    assert ts is not None
    assert (ts.year, ts.month, ts.day, ts.hour, ts.minute, ts.second) == (
        2026, 9, 12, 17, 4, 54,
    )
    assert ts.tzinfo is not None


def test_parse_last_update_returns_none_on_unparsable():
    assert _parse_last_update("no date here") is None


@pytest.mark.asyncio
async def test_fetch_returns_one_record_per_wanted_row():
    symbol_map, wanted = _patch_symbol_maps()
    fetcher = EstjtFetcher()

    with patch("atlas.fetchers.estjt_fetcher.SYMBOL_MAP", symbol_map), patch(
        "atlas.fetchers.estjt_fetcher.WANTED", wanted
    ), patch("atlas.fetchers.estjt_fetcher.requests.get") as mock_get:
        mock_get.return_value = MagicMock(
            text=SAMPLE_HTML, raise_for_status=lambda: None
        )
        records = await fetcher.fetch()

    # TEHRAN_QUOTE is excluded even though it's in SYMBOL_MAP
    assert {r.isin for r in records} == {"ons_tala", "geram18", "sekee_new"}
    ounce = next(r for r in records if r.isin == "ons_tala")
    assert ounce.price == 4348.0
    assert ounce.source_ts == _parse_last_update(REAL_UPDATE_TEXT)


@pytest.mark.asyncio
async def test_fetch_cache_busts_the_url():
    fetcher = EstjtFetcher(url="https://example.com/prices")

    with patch("atlas.fetchers.estjt_fetcher.requests.get") as mock_get:
        mock_get.return_value = MagicMock(text="<html></html>", raise_for_status=lambda: None)
        await fetcher.fetch()

    called_url = mock_get.call_args[0][0]
    assert called_url.startswith("https://example.com/prices?_cb=")
