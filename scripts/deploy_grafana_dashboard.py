"""Creates/updates the "Atlas" Grafana dashboard via the HTTP API.

Usage:
    GRAFANA_URL=https://grafana.alefcapital.ir GRAFANA_TOKEN=glsa_... \
        python scripts/deploy_grafana_dashboard.py

Requires a Grafana Service Account token (Admin role) in GRAFANA_TOKEN --
never hardcode it here or commit it anywhere. Safe to re-run: the
dashboard has a fixed uid and the POST uses overwrite=true, so this
updates the existing dashboard instead of duplicating it.

Assumes a Postgres/Timescale datasource named "quant_db" already
exists (it does, uid "quantdb", used by other server projects) and
that its role can read the `atlas` schema -- see README.md "Grafana"
for the one-time GRANT that makes that true.
"""
from __future__ import annotations

import os

import requests

GRAFANA_URL = os.environ.get("GRAFANA_URL", "https://grafana.alefcapital.ir")
GRAFANA_TOKEN = os.environ["GRAFANA_TOKEN"]
DATASOURCE_UID = "quantdb"
DASHBOARD_UID = "atlas-datasources"

# Every SQL query wraps the naive `time`/`received_at` columns in
# `AT TIME ZONE 'Asia/Tehran'` before comparing against now() or
# Grafana's $__timeFilter. atlas.raw_ticks stores naive Tehran local
# time (see CLAUDE.md invariant 9); Postgres would otherwise treat
# those naive values as UTC when compared to a timestamptz, silently
# shifting every displayed time by -03:30.


def _sql_panel(
    grid,
    title,
    panel_type,
    sql,
    unit="none",
    description="",
):
    return {
        "id": None,
        "gridPos": grid,
        "title": title,
        "type": panel_type,
        "description": description,
        "datasource": {"type": "grafana-postgresql-datasource", "uid": DATASOURCE_UID},
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "options": (
            {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}
            if panel_type == "timeseries"
            else {}
        ),
        "targets": [
            {
                "refId": "A",
                "datasource": {"type": "grafana-postgresql-datasource", "uid": DATASOURCE_UID},
                "rawSql": sql.strip(),
                "rawQuery": True,
                "format": "table" if panel_type == "table" else "time_series",
            }
        ],
    }


PANELS = [
    _sql_panel(
        {"x": 0, "y": 0, "w": 12, "h": 8},
        "Source health (freshness)",
        "table",
        """
        SELECT
          source,
          count(*) FILTER (
            WHERE (received_at AT TIME ZONE 'Asia/Tehran') > now() - interval '10 minutes'
          ) AS rows_last_10min,
          max(received_at) AT TIME ZONE 'Asia/Tehran' AS last_seen_tehran,
          extract(epoch FROM now() - (max(received_at) AT TIME ZONE 'Asia/Tehran'))::int AS seconds_since_last
        FROM atlas.raw_ticks
        GROUP BY source
        ORDER BY source
        """,
        description="Rows seen in the last 10 min and staleness per source, right now.",
    ),
    _sql_panel(
        {"x": 12, "y": 0, "w": 12, "h": 8},
        "Ingestion rate (instruments updated per minute)",
        "timeseries",
        """
        SELECT
          time AT TIME ZONE 'Asia/Tehran' AS "time",
          source,
          count(*) AS rows
        FROM atlas.raw_ticks
        WHERE $__timeFilter(time AT TIME ZONE 'Asia/Tehran')
        GROUP BY time, source
        ORDER BY time
        """,
        description="Distinct instruments updated per source per minute -- gaps mean a source stalled.",
    ),
    _sql_panel(
        {"x": 0, "y": 8, "w": 24, "h": 8},
        "Reporting lag (received_at - created_at)",
        "timeseries",
        """
        SELECT
          time AT TIME ZONE 'Asia/Tehran' AS "time",
          source,
          avg(extract(epoch FROM received_at - created_at)) AS avg_lag_seconds
        FROM atlas.raw_ticks
        WHERE $__timeFilter(time AT TIME ZONE 'Asia/Tehran')
        GROUP BY time, source
        ORDER BY time
        """,
        unit="s",
        description=(
            "How stale a source's own reported timestamp was when Atlas saw it. "
            "0 for sources with no independent timestamp (wallex, tabdeal) -- expected, not a fault."
        ),
    ),
    _sql_panel(
        {"x": 0, "y": 16, "w": 12, "h": 8},
        "NAV divergence: tadbir vs farabi (avg %, 31 gold funds)",
        "timeseries",
        """
        SELECT
          t.time AT TIME ZONE 'Asia/Tehran' AS "time",
          avg(abs(t.price - f.price) / NULLIF(f.price, 0) * 100) AS avg_pct_diff
        FROM
          (SELECT time, isin, price FROM atlas.raw_ticks WHERE source = 'tadbir') t
        JOIN
          (SELECT time, isin, price FROM atlas.raw_ticks WHERE source = 'farabi') f
          ON t.time = f.time AND t.isin = f.isin
        WHERE $__timeFilter(t.time AT TIME ZONE 'Asia/Tehran')
        GROUP BY t.time
        ORDER BY t.time
        """,
        unit="percent",
        description="Same 31 gold-fund ISINs, two independent providers -- average absolute price disagreement.",
    ),
    _sql_panel(
        {"x": 12, "y": 16, "w": 12, "h": 8},
        "Most divergent NAV funds right now",
        "table",
        """
        SELECT
          t.isin,
          t.price AS tadbir_price,
          f.price AS farabi_price,
          round((abs(t.price - f.price) / NULLIF(f.price, 0) * 100)::numeric, 3) AS pct_diff
        FROM
          (SELECT DISTINCT ON (isin) isin, price FROM atlas.raw_ticks WHERE source = 'tadbir' ORDER BY isin, time DESC) t
        JOIN
          (SELECT DISTINCT ON (isin) isin, price FROM atlas.raw_ticks WHERE source = 'farabi' ORDER BY isin, time DESC) f
          ON t.isin = f.isin
        ORDER BY pct_diff DESC
        LIMIT 15
        """,
        description="Latest snapshot, sorted by biggest tadbir/farabi disagreement.",
    ),
    _sql_panel(
        {"x": 0, "y": 24, "w": 12, "h": 8},
        "Gold gram 18k (geram18): estjt vs tabdeal",
        "timeseries",
        """
        SELECT time AT TIME ZONE 'Asia/Tehran' AS "time", source, price
        FROM atlas.raw_ticks
        WHERE isin = 'geram18' AND source IN ('estjt', 'tabdeal')
          AND $__timeFilter(time AT TIME ZONE 'Asia/Tehran')
        ORDER BY time
        """,
        unit="currencyIRT",
    ),
    _sql_panel(
        {"x": 12, "y": 24, "w": 12, "h": 8},
        "Gold gram 24k (geram24): estjt vs tabdeal",
        "timeseries",
        """
        SELECT time AT TIME ZONE 'Asia/Tehran' AS "time", source, price
        FROM atlas.raw_ticks
        WHERE isin = 'geram24' AND source IN ('estjt', 'tabdeal')
          AND $__timeFilter(time AT TIME ZONE 'Asia/Tehran')
        ORDER BY time
        """,
        unit="currencyIRT",
    ),
    _sql_panel(
        {"x": 0, "y": 32, "w": 12, "h": 8},
        "Gold ounce, USD (ons_tala): estjt vs goldprice",
        "timeseries",
        """
        SELECT time AT TIME ZONE 'Asia/Tehran' AS "time", source, price
        FROM atlas.raw_ticks
        WHERE isin = 'ons_tala' AND source IN ('estjt', 'goldprice')
          AND $__timeFilter(time AT TIME ZONE 'Asia/Tehran')
        ORDER BY time
        """,
        unit="currencyUSD",
        description="Same underlying international spot price, two independently-run scrapers.",
    ),
    _sql_panel(
        {"x": 12, "y": 32, "w": 12, "h": 8},
        "Coins (nim/rob/gerami): estjt vs tabdeal",
        "timeseries",
        """
        SELECT time AT TIME ZONE 'Asia/Tehran' AS "time", isin || '_' || source AS metric, price
        FROM atlas.raw_ticks
        WHERE isin IN ('nim', 'rob', 'gerami') AND source IN ('estjt', 'tabdeal')
          AND $__timeFilter(time AT TIME ZONE 'Asia/Tehran')
        ORDER BY time
        """,
        unit="currencyIRT",
    ),
]


def main() -> None:
    dashboard = {
        "uid": DASHBOARD_UID,
        "title": "Atlas",
        "tags": ["atlas"],
        "timezone": "Asia/Tehran",
        "editable": True,
        "graphTooltip": 1,
        "refresh": "30s",
        "time": {"from": "now-6h", "to": "now"},
        "panels": PANELS,
    }

    resp = requests.post(
        f"{GRAFANA_URL}/api/dashboards/db",
        headers={
            "Authorization": f"Bearer {GRAFANA_TOKEN}",
            "Content-Type": "application/json",
        },
        json={"dashboard": dashboard, "overwrite": True, "message": "deployed via deploy_grafana_dashboard.py"},
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()
    print(f"OK: {GRAFANA_URL}{result['url']}")


if __name__ == "__main__":
    main()
