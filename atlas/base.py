from __future__ import annotations

import abc
import dataclasses
import datetime as dt
from typing import Any


@dataclasses.dataclass(frozen=True, slots=True)
class RawRecord:
    """One raw observation.

    Column mapping in atlas.raw_ticks (deliberately mirrors the existing
    hist.gold_fund_nav / hist.gold_fundamental convention, with `nav`
    renamed to `price`):

        isin      -> isin        instrument identifier. Not always a
                                  literal ISIN (e.g. IME contract codes
                                  like "LeadIngot") -- kept as the
                                  field/column name to match the
                                  server's existing tables, not as a
                                  format guarantee.
        ts        -> time, received_at
                                  wall-clock time when Atlas fetched
                                  this record. Deliberately NOT the
                                  source's own timestamp. `time` is
                                  truncated to the minute floor and
                                  used in an UPSERT (see
                                  TimescaleSink) -- matching
                                  TSE-GOLD-ALGO's AsyncDataBuffer, this
                                  makes atlas.raw_ticks a
                                  latest-value-per-minute history, not
                                  a full tick log: a second poll in the
                                  same minute overwrites the first
                                  rather than adding a row. `received_at`
                                  keeps `ts` at full precision instead.
        source_ts -> created_at  the source's own reported timestamp
                                  (e.g. IME's LastUpdate). Defaults to
                                  `ts` when a datasource has no
                                  independent timestamp of its own.
        price     -> price       nullable: not every datasource has one
                                  scalar price to surface.
        payload   -> payload     the full raw record, unparsed.
    """

    isin: str
    ts: dt.datetime
    price: float | None
    payload: dict[str, Any]
    source_ts: dt.datetime | None = None

    def resolved_source_ts(self) -> dt.datetime:
        return self.source_ts if self.source_ts is not None else self.ts


class Fetcher(abc.ABC):
    """Base class for one datasource.

    A new datasource is added by subclassing this and registering it in
    `config/datasources.yaml` -- nothing else in Atlas needs to change.
    """

    #: Short label for this datasource -- used as the Redis key prefix
    #: and written into the `source` column (varchar(50)) in raw_ticks.
    #: Set on subclasses, e.g. "ime".
    name: str

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
