from __future__ import annotations

import datetime as dt
import re
import time
from zoneinfo import ZoneInfo

import jdatetime
import requests
from bs4 import BeautifulSoup

from atlas.base import Fetcher, RawRecord

# estjt.ir gold/coin prices -- no JSON API, HTML scrape.
#
# Reference: user-supplied estjt_fetcher.py script. The page sits
# behind LiteSpeed Cache, so every request adds a cache-busting query
# param + no-cache headers -- without that, repeated polls can get the
# same cached response back instead of a fresh one.

URL = "https://www.estjt.ir"
TEHRAN_TZ = ZoneInfo("Asia/Tehran")

_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

_JALALI_MONTHS = {
    "فروردین": 1,
    "اردیبهشت": 2,
    "خرداد": 3,
    "تیر": 4,
    "مرداد": 5,
    "شهریور": 6,
    "مهر": 7,
    "آبان": 8,
    "آذر": 9,
    "دی": 10,
    "بهمن": 11,
    "اسفند": 12,
}

# Persian row label -> short isin-like code.
SYMBOL_MAP = {
    "انس طلا": "ons_tala",
    "مظنه تهران": "mazaneh_tehran",
    "طلا ۱۸ عیار": "geram18",
    "طلای ۲۴ عیار": "geram24",
    "سکه طرح جدید": "sekee_new",
    "سکه طرح قدیم": "sekee_old",
    "نیم سکه": "nim",
    "ربع سکه": "rob",
    "سکه گرمی": "gerami",
}

# Only these rows are kept -- matches SYMBOL_MAP minus "mazaneh_tehran"
# (the Tehran gold-market quote), which the source script deliberately
# excluded.
WANTED = frozenset(SYMBOL_MAP) - {"مظنه تهران"}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "If-Modified-Since": "0",
}


def _fa_to_en_digits(s: str) -> str:
    return s.translate(_DIGIT_MAP)


def _clean_number(raw: str) -> float | None:
    """Parses a Persian-formatted price like "24.147.100" (Arabic
    decimal separator U+066B used here as a THOUSANDS separator, not a
    decimal point) or "$ 4348" into a float."""
    s = _fa_to_en_digits(raw).replace("$", "").strip()
    s = s.replace("٫", "").replace(",", "").replace("،", "")
    s = re.sub(r"[^\d.]", "", s)
    return float(s) if s else None


def _parse_last_update(text: str) -> dt.datetime | None:
    """Parses e.g. "Last update: 21 Shahrivar 1405 - 15:24:42" (Jalali)
    into an Asia/Tehran-aware datetime. Returns None on anything
    unparsable -- RawRecord.source_ts already falls back to `ts`."""
    text = _fa_to_en_digits(text)
    m = re.search(r"(\d{1,2})\s+(\S+)\s+(\d{3,4})\s*-\s*(\d{1,2}):(\d{2}):(\d{2})", text)
    if not m:
        return None
    day, month_name, year, hh, mm, ss = m.groups()
    month_num = _JALALI_MONTHS.get(month_name)
    if month_num is None:
        return None
    jd = jdatetime.datetime(int(year), month_num, int(day), int(hh), int(mm), int(ss))
    return jd.togregorian().replace(tzinfo=TEHRAN_TZ)


def _parse_price_block(soup: BeautifulSoup, css_class: str) -> list[tuple[str, float, dt.datetime | None]]:
    """One .instant-price block (gold or coin) -> (name, price, last_update)."""
    block = soup.select_one(f"div.instant-price.{css_class}")
    if block is None:
        return []

    update_p = block.select_one("p.text-center")
    last_update = _parse_last_update(update_p.get_text(strip=True)) if update_p else None

    rows = []
    for tr in block.select("table tr"):
        name_td = tr.select_one("td.name")
        price_td = tr.select_one("td.price")
        if not name_td or not price_td:
            continue
        name = name_td.get_text(strip=True)
        if name not in WANTED:
            continue
        price = _clean_number(price_td.get_text(strip=True))
        if price is None:
            continue
        rows.append((name, price, last_update))
    return rows


class EstjtFetcher(Fetcher):
    """estjt.ir gold/coin prices, cache-busted every poll."""

    name = "estjt"

    async def fetch(self) -> list[RawRecord]:
        url = self.config.get("url", URL)
        sep = "&" if "?" in url else "?"
        cache_busted_url = f"{url}{sep}_cb={int(time.time() * 1000)}"

        resp = requests.get(cache_busted_url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        resp.encoding = "utf-8"

        soup = BeautifulSoup(resp.text, "html.parser")
        now = dt.datetime.now(TEHRAN_TZ)

        records = []
        for css_class in ("instant-price-gold", "instant-price-coin"):
            for name, price, last_update in _parse_price_block(soup, css_class):
                isin = SYMBOL_MAP.get(name, name)
                records.append(
                    RawRecord(
                        isin=isin,
                        ts=now,
                        price=price,
                        payload={"name": name, "price": price},
                        source_ts=last_update,
                    )
                )
        return records
