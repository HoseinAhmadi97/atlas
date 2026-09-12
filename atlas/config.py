from __future__ import annotations

import dataclasses
import datetime as dt
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from atlas.schedule import ScheduleConfig


@dataclasses.dataclass(frozen=True, slots=True)
class DatasourceConfig:
    name: str
    module: str
    cls: str
    interval_s: float
    enabled: bool
    fetcher_kwargs: dict[str, Any]
    redis_ttl_s: int | None
    schedule: ScheduleConfig


@dataclasses.dataclass(frozen=True, slots=True)
class AtlasConfig:
    redis_host: str
    redis_port: int
    redis_db: int
    postgres_dsn: str
    datasources: list[DatasourceConfig]


def _parse_clock_time(value: str) -> dt.time:
    return dt.datetime.strptime(value, "%H:%M").time()


def _parse_schedule(entry: dict[str, Any]) -> ScheduleConfig:
    raw = entry.get("schedule")
    if not raw:
        return ScheduleConfig()  # no restriction -- fetch any time
    return ScheduleConfig(
        workdays_only=bool(raw.get("workdays_only", False)),
        start=_parse_clock_time(raw["start"]) if raw.get("start") else None,
        end=_parse_clock_time(raw["end"]) if raw.get("end") else None,
    )


def load_config(path: str | Path = "config/datasources.yaml") -> AtlasConfig:
    load_dotenv()  # .env, if present, populates os.environ first

    raw = yaml.safe_load(Path(path).read_text())
    datasources = []
    for entry in raw.get("datasources", []):
        datasources.append(
            DatasourceConfig(
                name=entry["name"],
                module=entry["module"],
                cls=entry["class"],
                interval_s=float(entry.get("interval_s", 5)),
                enabled=bool(entry.get("enabled", True)),
                fetcher_kwargs=entry.get("kwargs", {}),
                redis_ttl_s=entry.get("redis", {}).get("ttl_s"),
                schedule=_parse_schedule(entry),
            )
        )

    return AtlasConfig(
        redis_host=os.environ.get("ATLAS_REDIS_HOST", "127.0.0.1"),
        redis_port=int(os.environ.get("ATLAS_REDIS_PORT", "6379")),
        redis_db=int(os.environ.get("ATLAS_REDIS_DB", "0")),
        postgres_dsn=os.environ["ATLAS_PG_DSN"],
        datasources=datasources,
    )
