"""Central logging configuration.

File logs rotate at midnight and keep 30 days of history. ERROR+ records are
additionally forwarded to Telegram via alerts.TelegramHandler. Call setup()
once at the start of any entry point; it is idempotent.
"""
from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler

import config

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_configured = False


def setup(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return

    config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(_FORMAT)

    file_handler = TimedRotatingFileHandler(
        config.LOG_PATH, when="midnight", backupCount=30, encoding="utf-8", utc=True
    )
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(fmt)

    # ERROR+ -> Telegram (no-op if Telegram unconfigured)
    from alerts import TelegramHandler
    tg_handler = TelegramHandler()
    tg_handler.setLevel(logging.ERROR)
    tg_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    for h in (file_handler, stream_handler, tg_handler):
        root.addHandler(h)

    _configured = True
