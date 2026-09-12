import datetime as dt

from atlas.config import load_config

YAML_CONTENT = """
datasources:
  - name: scheduled
    module: atlas.fetchers.example_fetcher
    class: ExampleFetcher
    interval_s: 5
    enabled: true
    kwargs: {}
    schedule:
      workdays_only: true
      start: "12:00"
      end: "18:00"

  - name: unscheduled
    module: atlas.fetchers.example_fetcher
    class: ExampleFetcher
    interval_s: 5
    enabled: true
    kwargs: {}
"""


def test_schedule_block_is_parsed(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_PG_DSN", "postgresql://fake")
    yaml_path = tmp_path / "datasources.yaml"
    yaml_path.write_text(YAML_CONTENT)

    config = load_config(yaml_path)
    by_name = {ds.name: ds for ds in config.datasources}

    scheduled = by_name["scheduled"].schedule
    assert scheduled.workdays_only is True
    assert scheduled.start == dt.time(12, 0)
    assert scheduled.end == dt.time(18, 0)


def test_missing_schedule_block_means_no_restriction(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_PG_DSN", "postgresql://fake")
    yaml_path = tmp_path / "datasources.yaml"
    yaml_path.write_text(YAML_CONTENT)

    config = load_config(yaml_path)
    unscheduled = next(ds for ds in config.datasources if ds.name == "unscheduled").schedule

    assert unscheduled.workdays_only is False
    assert unscheduled.start is None
    assert unscheduled.end is None
