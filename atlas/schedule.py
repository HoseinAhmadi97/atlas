from __future__ import annotations

import dataclasses
import datetime as dt
from zoneinfo import ZoneInfo

TEHRAN_TZ = ZoneInfo("Asia/Tehran")

# Iran's work week: Saturday through Wednesday. datetime.weekday() is
# Monday=0 .. Sunday=6, so that's {5, 6, 0, 1, 2}. Thursday(3)/Friday(4)
# are the weekend.
_WORKDAY_WEEKDAYS = frozenset({5, 6, 0, 1, 2})


@dataclasses.dataclass(frozen=True, slots=True)
class ScheduleConfig:
    """When a datasource is allowed to fetch.

    Every field is optional and defaults to "no restriction" on that
    dimension -- a bare `ScheduleConfig()` allows fetching at any time,
    which is the default for a datasource with no `schedule:` block.
    """

    workdays_only: bool = False
    start: dt.time | None = None
    end: dt.time | None = None

    def allows(self, now: dt.datetime) -> bool:
        if self.workdays_only and now.weekday() not in _WORKDAY_WEEKDAYS:
            return False
        if self.start is not None and now.time() < self.start:
            return False
        if self.end is not None and now.time() > self.end:
            return False
        return True


def now_tehran() -> dt.datetime:
    return dt.datetime.now(TEHRAN_TZ)
