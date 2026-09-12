from __future__ import annotations

import abc
import dataclasses
import datetime as dt
from typing import Any


@dataclasses.dataclass(frozen=True, slots=True)
class RawRecord:
    """One raw observation. `payload` is stored as-is, unparsed.

    `source` is provenance, not grouping: it says exactly where this
    record physically came from (a URL, an endpoint name, "offline-demo").
    `datasource` (the config/registry key, e.g. "ime") is the grouping
    used for Redis keys and the `datasource` column -- a single
    datasource can still carry a per-record `source` if it ever reads
    from more than one endpoint.
    """

    symbol: str
    ts: dt.datetime
    source: str
    payload: dict[str, Any]


class Fetcher(abc.ABC):
    """Base class for one datasource.

    A new datasource is added by subclassing this and registering it in
    `config/datasources.yaml` -- nothing else in Atlas needs to change.
    """

    #: Unique short name, used as the Redis key prefix and the
    #: `datasource` column value in raw_ticks. Set on subclasses.
    name: str

    #: Where this datasource's data physically comes from -- a URL or a
    #: short human-readable label. Used as the default `source` on the
    #: RawRecords this fetcher produces. Set on subclasses.
    source: str

    def __init__(self, **config: Any) -> None:
        self.config = config

    @abc.abstractmethod
    async def fetch(self) -> list[RawRecord]:
        """Return the current raw observations for this datasource.

        Must not raise for "no new data" -- return an empty list instead.
        Only raise for an actual fetch failure; the runner logs it and
        retries on the next interval without touching other datasources.
        """
        raise NotImplementedError
