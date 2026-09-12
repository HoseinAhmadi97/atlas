import asyncio
import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from atlas.config import DatasourceConfig
from atlas.runner import _run_datasource
from atlas.schedule import ScheduleConfig

TEHRAN_TZ = ZoneInfo("Asia/Tehran")


async def _run_briefly(ds):
    with patch(
        "atlas.fetchers.example_fetcher.ExampleFetcher.fetch", new_callable=AsyncMock
    ) as mock_fetch:
        mock_fetch.return_value = []
        task = asyncio.create_task(
            _run_datasource(ds, redis_sink=MagicMock(), timescale_sink=MagicMock())
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    return mock_fetch


@pytest.mark.asyncio
async def test_outside_schedule_window_never_calls_fetch():
    ds = DatasourceConfig(
        name="scheduled",
        module="atlas.fetchers.example_fetcher",
        cls="ExampleFetcher",
        interval_s=0.01,
        enabled=True,
        fetcher_kwargs={},
        schedule=ScheduleConfig(workdays_only=True),
    )
    thursday_noon = dt.datetime(2026, 9, 10, 12, 0, tzinfo=TEHRAN_TZ)  # weekend

    with patch("atlas.runner.now_tehran", return_value=thursday_noon):
        mock_fetch = await _run_briefly(ds)

    mock_fetch.assert_not_called()


@pytest.mark.asyncio
async def test_inside_schedule_window_calls_fetch():
    ds = DatasourceConfig(
        name="scheduled",
        module="atlas.fetchers.example_fetcher",
        cls="ExampleFetcher",
        interval_s=0.01,
        enabled=True,
        fetcher_kwargs={},
        schedule=ScheduleConfig(workdays_only=True),
    )
    saturday_noon = dt.datetime(2026, 9, 12, 12, 0, tzinfo=TEHRAN_TZ)  # workday

    with patch("atlas.runner.now_tehran", return_value=saturday_noon):
        mock_fetch = await _run_briefly(ds)

    mock_fetch.assert_called()
