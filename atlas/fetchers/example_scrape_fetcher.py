from __future__ import annotations

import datetime as dt

import requests
from bs4 import BeautifulSoup

from atlas.base import Fetcher, RawRecord

# Template for a datasource with no JSON API -- only an HTML page to
# scrape. The `Fetcher` contract doesn't care how `fetch()` gets its
# data (JSON API, HTML scrape, anything else); this is the scraping
# variant of atlas/fetchers/example_fetcher.py's template.
#
# Copy this file for a real scraped datasource:
#   1. rename the class and `name`
#   2. point `url` at the real page and adjust the BeautifulSoup
#      selectors in `_parse()` to match its actual markup
#   3. add an entry in config/datasources.yaml


class ExampleScrapeFetcher(Fetcher):
    """Demo HTML-scraping fetcher.

    Uses a fixed HTML snippet instead of a real HTTP request so it stays
    runnable offline in dev/tests; a real fetcher replaces `fetch()`'s
    body with an actual `requests.get(self.config["url"])`.
    """

    name = "example_scrape"
    source = "offline-demo-html"

    _DEMO_HTML = """
    <table id="prices">
      <tr><td class="symbol">DEMO1</td><td class="price">150.25</td></tr>
      <tr><td class="symbol">DEMO2</td><td class="price">98.10</td></tr>
    </table>
    """

    def _parse(self, html: str, source: str) -> list[RawRecord]:
        soup = BeautifulSoup(html, "html.parser")
        now = dt.datetime.now(dt.timezone.utc)
        records = []
        for row in soup.select("#prices tr"):
            symbol = row.select_one(".symbol").text.strip()
            price = float(row.select_one(".price").text.strip())
            records.append(
                RawRecord(symbol=symbol, ts=now, source=source, payload={"price": price})
            )
        return records

    async def fetch(self) -> list[RawRecord]:
        url = self.config.get("url")
        if url:
            resp = requests.get(url, timeout=(3, 10))
            resp.raise_for_status()
            html = resp.text
        else:
            url = self.source  # offline demo path
            html = self._DEMO_HTML
        return self._parse(html, source=url)
