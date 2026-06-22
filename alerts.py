"""Telegram alerting for critical failures.

`notify()` sends a message; it is a no-op when Telegram isn't configured and
never raises (alerting must not break the pipeline). `TelegramHandler` is a
logging handler that forwards ERROR+ records to Telegram, so anything logged at
error level (publish failures, research failures, slots that can't produce a
compliant post) reaches you without scattering explicit notify() calls.
"""
from __future__ import annotations

import logging

import requests

import config

# Logger used for *internal* alert failures. Kept below ERROR on purpose so it
# can't re-trigger the ERROR-level TelegramHandler (no recursion).
_log = logging.getLogger("calm_money.alerts")


def configured() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


def notify(text: str) -> bool:
    """Send a Telegram message. Returns True on success; never raises."""
    if not configured():
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            data={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": text[:4000],
                "disable_web_page_preview": "true",
            },
            timeout=15,
        )
        if not r.ok:
            _log.warning("telegram sendMessage failed: %s %s", r.status_code, r.text[:200])
        return r.ok
    except requests.RequestException as e:
        _log.warning("telegram notify error: %s", e)
        return False


class TelegramHandler(logging.Handler):
    """Routes ERROR+ log records to Telegram (best-effort)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if not configured():
                return
            notify(f"⚠️ Calm Money Daily\n{self.format(record)}")
        except Exception:  # a logging handler must never raise
            pass
