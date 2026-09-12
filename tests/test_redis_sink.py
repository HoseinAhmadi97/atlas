import datetime as dt

import fakeredis

from atlas.base import RawRecord
from atlas.sinks.redis_sink import RedisSink


def test_write_then_read_roundtrip():
    sink = RedisSink(fakeredis.FakeRedis())
    ts = dt.datetime(2026, 9, 12, 8, 45, tzinfo=dt.timezone.utc)
    records = [RawRecord(isin="FOO", ts=ts, price=123.4, payload={"price": 123.4})]

    sink.write("unit-test", records)
    got = sink.read("unit-test", "FOO")

    assert got["isin"] == "FOO"
    assert got["source"] == "unit-test"
    assert got["price"] == 123.4
    assert got["payload"]["price"] == 123.4


def test_missing_key_returns_none():
    sink = RedisSink(fakeredis.FakeRedis())
    assert sink.read("unit-test", "NOPE") is None


def test_write_has_no_expiry():
    client = fakeredis.FakeRedis()
    sink = RedisSink(client)
    ts = dt.datetime.now(dt.timezone.utc)
    sink.write("unit-test", [RawRecord(isin="FOO", ts=ts, price=None, payload={})])

    assert client.ttl(sink.key("unit-test", "FOO")) == -1  # -1: key exists, no TTL


def test_second_write_overwrites_the_snapshot():
    client = fakeredis.FakeRedis()
    sink = RedisSink(client)
    ts = dt.datetime.now(dt.timezone.utc)

    sink.write("unit-test", [RawRecord(isin="FOO", ts=ts, price=1.0, payload={})])
    sink.write("unit-test", [RawRecord(isin="FOO", ts=ts, price=2.0, payload={})])

    assert sink.read("unit-test", "FOO")["price"] == 2.0
