import datetime as dt
from zoneinfo import ZoneInfo

from atlas.schedule import ScheduleConfig

TEHRAN_TZ = ZoneInfo("Asia/Tehran")


def _at(year, month, day, hour, minute):
    return dt.datetime(year, month, day, hour, minute, tzinfo=TEHRAN_TZ)


def test_default_schedule_allows_anytime():
    schedule = ScheduleConfig()
    assert schedule.allows(_at(2026, 9, 12, 3, 0))  # Saturday, 03:00
    assert schedule.allows(_at(2026, 9, 10, 23, 59))  # Thursday, weekend


def test_workdays_only_rejects_thursday_and_friday():
    schedule = ScheduleConfig(workdays_only=True)
    thursday = _at(2026, 9, 10, 13, 0)
    friday = _at(2026, 9, 11, 13, 0)
    saturday = _at(2026, 9, 12, 13, 0)

    assert thursday.weekday() == 3
    assert friday.weekday() == 4
    assert not schedule.allows(thursday)
    assert not schedule.allows(friday)
    assert schedule.allows(saturday)


def test_start_end_window_is_inclusive():
    schedule = ScheduleConfig(start=dt.time(12, 0), end=dt.time(18, 0))

    assert schedule.allows(_at(2026, 9, 12, 12, 0))   # exactly start
    assert schedule.allows(_at(2026, 9, 12, 18, 0))   # exactly end
    assert schedule.allows(_at(2026, 9, 12, 15, 0))   # inside
    assert not schedule.allows(_at(2026, 9, 12, 11, 59))
    assert not schedule.allows(_at(2026, 9, 12, 18, 1))


def test_workdays_and_time_window_combine():
    schedule = ScheduleConfig(workdays_only=True, start=dt.time(12, 0), end=dt.time(18, 0))

    assert schedule.allows(_at(2026, 9, 12, 13, 0))       # Saturday, in window
    assert not schedule.allows(_at(2026, 9, 12, 8, 0))    # Saturday, before window
    assert not schedule.allows(_at(2026, 9, 11, 13, 0))   # Friday, in time window but weekend
