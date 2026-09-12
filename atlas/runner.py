from __future__ import annotations

import asyncio
import logging

import redis

from atlas.config import AtlasConfig, DatasourceConfig, load_config
from atlas.registry import load_fetcher
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

    while True:
        try:
            records = await fetcher.fetch()
        except Exception:
            # One datasource's failure must never take down the others.
            logger.exception("fetch failed for %s", ds.name)
            await asyncio.sleep(ds.interval_s)
            continue

        if records:
            try:
                redis_sink.write(ds.name, records, ttl_s=ds.redis_ttl_s)
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
