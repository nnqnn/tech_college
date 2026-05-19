from __future__ import annotations

import logging


def configure_logging(*, structured: bool) -> None:
    if structured:
        try:
            from pythonjsonlogger import json as jsonlogger
        except ImportError:
            structured = False

    handler = logging.StreamHandler()
    if structured:
        formatter = jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
    else:
        formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
