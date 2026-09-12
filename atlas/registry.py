from __future__ import annotations

import importlib
from typing import Any

from atlas.base import Fetcher


def load_fetcher(module: str, cls: str, **config: Any) -> Fetcher:
    """Instantiate a Fetcher from its dotted module path + class name.

    This is the only place that turns a `config/datasources.yaml` entry
    into a running fetcher -- adding a datasource never means editing
    this function, only adding a config entry and a fetcher module.
    """
    mod = importlib.import_module(module)
    fetcher_cls = getattr(mod, cls)
    if not issubclass(fetcher_cls, Fetcher):
        raise TypeError(f"{module}.{cls} is not a Fetcher subclass")
    return fetcher_cls(**config)
