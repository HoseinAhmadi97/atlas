"""Idempotent DB setup: creates raw_ticks and tries the hypertable
conversion. Safe to re-run.

Usage: python scripts/bootstrap_db.py
Requires ATLAS_PG_DSN in the environment (or .env).
"""
from __future__ import annotations

import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "atlas" / "db" / "schema.sql"


def main() -> None:
    load_dotenv()
    dsn = os.environ["ATLAS_PG_DSN"]

    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            # Only the CREATE TABLE / CREATE INDEX statements -- the
            # hypertable conversion is commented out in schema.sql on
            # purpose (see README "Prerequisites") and handled below.
            uncommented = "\n".join(
                line
                for line in SCHEMA_PATH.read_text().splitlines()
                if not line.strip().startswith("--")
            )
            statements = [s.strip() for s in uncommented.split(";") if s.strip()]
            for stmt in statements:
                cur.execute(stmt)
        conn.commit()
        print("raw_ticks table + index: OK")

        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'")
            has_timescale = cur.fetchone() is not None

        if not has_timescale:
            print(
                "timescaledb extension not installed -- raw_ticks stays a "
                "plain table. See README.md 'Prerequisites' for the apt "
                "install + CREATE EXTENSION steps (needs sudo)."
            )
            return

        with conn.cursor() as cur:
            cur.execute(
                "SELECT create_hypertable(%s, %s, if_not_exists => TRUE)",
                ("raw_ticks", "ts"),
            )
        conn.commit()
        print("raw_ticks hypertable: OK")


if __name__ == "__main__":
    main()
