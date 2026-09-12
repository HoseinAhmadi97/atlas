import datetime as dt
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from atlas.base import RawRecord
from atlas.sinks.timescale_sink import TimescaleSink, _naive_tehran

TEHRAN_TZ = ZoneInfo("Asia/Tehran")


def test_naive_tehran_converts_aware_datetime():
    utc_ts = dt.datetime(2026, 9, 12, 13, 25, 15, tzinfo=dt.timezone.utc)
    naive = _naive_tehran(utc_ts)

    assert naive.tzinfo is None
    assert naive == dt.datetime(2026, 9, 12, 16, 55, 15)  # UTC+3:30


def test_naive_tehran_passes_through_naive_datetime():
    already_naive = dt.datetime(2026, 9, 12, 16, 55, 15)
    assert _naive_tehran(already_naive) == already_naive


def test_write_passes_seven_columns_in_schema_order():
    with patch("atlas.sinks.timescale_sink.psycopg2.connect") as mock_connect, patch(
        "atlas.sinks.timescale_sink.psycopg2.extras.execute_values"
    ) as mock_execute_values:
        mock_conn = MagicMock()
        mock_conn.closed = False
        mock_connect.return_value = mock_conn

        sink = TimescaleSink("postgresql://fake")
        ts = dt.datetime(2026, 9, 12, 16, 48, 0, tzinfo=TEHRAN_TZ)
        record = RawRecord(isin="LeadIngot", ts=ts, price=4710000.0, payload={"a": 1})
        sink.write("ime", [record])

    args, _ = mock_execute_values.call_args
    _cur, _sql, rows = args
    (isin, time_, price, created_at, received_at, source, payload) = rows[0]

    assert isin == "LeadIngot"
    assert time_ == dt.datetime(2026, 9, 12, 16, 48, 0)
    assert price == 4710000.0
    assert created_at == time_  # no source_ts given -> falls back to ts
    assert received_at == time_
    assert source == "ime"
    assert payload == '{"a": 1}'


def test_failed_write_forces_reconnect_on_next_call():
    """Regression: a failed INSERT used to leave the connection in an
    aborted-transaction state forever (never closed, never rolled
    back), so every write after the first failure would silently keep
    failing until the whole process restarted."""
    with patch("atlas.sinks.timescale_sink.psycopg2.connect") as mock_connect, patch(
        "atlas.sinks.timescale_sink.psycopg2.extras.execute_values"
    ) as mock_execute_values:
        first_conn = MagicMock()
        first_conn.closed = False
        first_conn.close.side_effect = lambda: setattr(first_conn, "closed", True)
        second_conn = MagicMock()
        second_conn.closed = False
        mock_connect.side_effect = [first_conn, second_conn]
        mock_execute_values.side_effect = [Exception("boom"), None]

        sink = TimescaleSink("postgresql://fake")
        ts = dt.datetime(2026, 9, 12, 16, 48, 0, tzinfo=TEHRAN_TZ)
        record = RawRecord(isin="LeadIngot", ts=ts, price=1.0, payload={})

        try:
            sink.write("ime", [record])
        except Exception:
            pass

        first_conn.rollback.assert_called_once()
        first_conn.close.assert_called_once()

        sink.write("ime", [record])  # must reconnect, not reuse the aborted connection

    assert mock_connect.call_count == 2
    second_conn.commit.assert_called_once()
