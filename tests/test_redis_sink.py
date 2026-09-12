import datetime as dt

import fakeredis

from atlas.base import RawRecord
from atlas.sinks.redis_sink import RedisSink


def test_write_then_read_roundtrip():
    sink = RedisSink(fakeredis.FakeRedis(), default_ttl_s=60)
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


def test_ttl_is_applied():
    client = fakeredis.FakeRedis()
    sink = RedisSink(client, default_ttl_s=30)
    ts = dt.datetime.now(dt.timezone.utc)
    sink.write("unit-test", [RawRecord(isin="FOO", ts=ts, price=None, payload={})])

    ttl = client.ttl(sink.key("unit-test", "FOO"))
    assert 0 < ttl <= 30
