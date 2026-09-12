from __future__ import annotations

import asyncio
import logging

import redis

from atlas.config import AtlasConfig, DatasourceConfig, load_config
from atlas.registry import load_fetcher
from atlas.schedule import now_tehran
from atlas.sinks import RedisSink, TimescaleSink

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("atlas.runner")


async def _run_datasource(
    ds: DatasourceConfig,
    redis_sink: RedisSink,
    timescale_sink: TimescaleSink,
) -> None:
    fetcher = load_fetcher(ds.module, ds.cls, **ds.fetcher_kwargs)
    logger.info("starting %s (interval=%ss)", ds.name, ds.interval_s)

    was_in_window = True  # log once if we start up already outside the window
    while True:
        in_window = ds.schedule.allows(now_tehran())
        if in_window != was_in_window:
            logger.info(
                "%s: %s scheduled window",
                ds.name,
                "entering" if in_window else "leaving",
            )
            was_in_window = in_window

        if not in_window:
            await asyncio.sleep(ds.interval_s)
            continue

        try:
            records = await fetcher.fetch()
        except Exception:
            # One datasource's failure must never take down the others.
            logger.exception("fetch failed for %s", ds.name)
            await asyncio.sleep(ds.interval_s)
            continue

        if records:
            try:
                redis_sink.write(ds.name, records)
            except Exception:
                logger.exception("redis write failed for %s", ds.name)
            try:
                timescale_sink.write(ds.name, records)
            except Exception:
                logger.exception("timescale write failed for %s", ds.name)

        await asyncio.sleep(ds.interval_s)


async def main_async(config: AtlasConfig) -> None:
    redis_client = redis.Redis(host=config.redis_host, port=config.redis_port, db=config.redis_db)
    redis_sink = RedisSink(redis_client)
    timescale_sink = TimescaleSink(config.postgres_dsn)

    enabled = [ds for ds in config.datasources if ds.enabled]
    if not enabled:
        logger.warning("no datasources enabled in config -- nothing to do")
        return

    await asyncio.gather(*(_run_datasource(ds, redis_sink, timescale_sink) for ds in enabled))


def main() -> None:
    config = load_config()
    asyncio.run(main_async(config))


if __name__ == "__main__":
    main()
