"""Static gold-fund ISIN list, copied from TSE-GOLD-ALGO's utils/base.py
(`gold_isin`), shared by the nav_tadbir and nav_farabi fetchers.

Not read at runtime from market_fetcher's `all_tickers_info` Redis key:
that key has no TTL and can be stale or simply absent (market_fetcher
isn't always running). Update this list by hand if utils/base.py's
gold_isin changes.
"""
from __future__ import annotations

GOLD_ISINS = [
    "IRTKLOTF0001", "IRTKZARF0001", "IRTKKIAN0001", "IRTKMOFD0001",
    "IRTKROBA0001", "IRTKZARA0001", "IRTKZFAM0001", "IRTKNAFS0001",
    "IRTKGANJ0001", "IRTKNAAB0001", "IRTKALTN0001", "IRTKJAVA0001",
    "IRTKTABA0001", "IRTKLIAN0001", "IRTKZARV0001", "IRTKDRKS0001",
    "IRTKATSH0001", "IRTKGHIR0001", "IRTKGOLN0001", "IRTKZOMR0001",
    "IRTKEMRL0001", "IRTKROSE0001", "IRTKDORN0001", "IRTKZARG0001",
    "IRTKRITO0001", "IRTKROZG0001", "IRTKJAMF0001", "IRTKNGIN0001",
    "IRTKGOLD0001", "IRTKHAMY0001", "IRTKMIRA0001",
]
