import datetime as dt

import fakeredis

from atlas.base import RawRecord
from atlas.sinks.redis_sink import RedisSink


def test_write_then_read_roundtrip():
    sink = RedisSink(fakeredis.FakeRedis(), default_ttl_s=60)
    ts = dt.datetime(2026, 9, 12, 8, 45, tzinfo=dt.timezone.utc)
    records = [RawRecord(symbol="FOO", ts=ts, source="unit-test", payload={"price": 123.4})]

    sink.write("demo", records)
    got = sink.read("demo", "FOO")

    assert got["symbol"] == "FOO"
    assert got["source"] == "unit-test"
    assert got["payload"]["price"] == 123.4


def test_missing_key_returns_none():
    sink = RedisSink(fakeredis.FakeRedis())
    assert sink.read("demo", "NOPE") is None


def test_ttl_is_applied():
    client = fakeredis.FakeRedis()
    sink = RedisSink(client, default_ttl_s=30)
    ts = dt.datetime.now(dt.timezone.utc)
    sink.write("demo", [RawRecord(symbol="FOO", ts=ts, source="unit-test", payload={})])

    ttl = client.ttl(sink.key("demo", "FOO"))
    assert 0 < ttl <= 30
