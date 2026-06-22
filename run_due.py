"""Entry point: publish whichever posting slot is currently due.

Designed to be invoked by a Windows batch file on a schedule (Task Scheduler).
On each run it looks at today's four posting slots in US Eastern time and
publishes any slot whose time has arrived within the catch-up window and that
hasn't already been posted. Normally Task Scheduler fires it near a slot time so
exactly one slot runs; the catch-up window covers a PC that was asleep.

    python run_due.py                 # post any due-but-unposted slot now
    python run_due.py --slot quote    # force one format, ignore timing
    python run_due.py --force         # treat the nearest slot as due now
    python run_due.py --catchup-hours 6
    python run_due.py --list          # show today's slots and their status

Set DRY_RUN=1 in .env to render + stage locally without calling Facebook.
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta

import pytz

import config
import logging_setup
from db import init_db


def _todays_slots():
    """Return [(format_type, scheduled_local, scheduled_utc_iso), ...] for today (ET)."""
    tz = pytz.timezone(config.TIMEZONE_TARGET)
    now_local = datetime.now(tz)
    out = []
    for hour, minute, fmt in config.POSTING_SLOTS:
        local = tz.localize(datetime(now_local.year, now_local.month, now_local.day, hour, minute))
        out.append((fmt, local, local.astimezone(pytz.utc).isoformat()))
    return out


def _print_status() -> None:
    import store
    now_utc = datetime.now(pytz.utc)
    print(f"Now: {now_utc.isoformat()} (UTC)\nToday's slots (US Eastern):")
    for fmt, local, sched_iso in _todays_slots():
        posted = store.slot_already_posted(sched_iso)
        due = now_utc >= datetime.fromisoformat(sched_iso)
        state = "posted" if posted else ("DUE" if due else "upcoming")
        print(f"  {local.strftime('%I:%M %p %Z')}  {fmt:<9}  -> {state}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Publish the posting slot that is due now.")
    ap.add_argument("--slot", choices=config.FORMAT_TYPES, help="Force this format now, ignoring timing.")
    ap.add_argument("--force", action="store_true", help="Treat the nearest slot as due now.")
    ap.add_argument("--catchup-hours", type=float, default=4.0,
                    help="Max hours a slot can be late and still post (default 4).")
    ap.add_argument("--list", action="store_true", help="Show today's slots and exit.")
    args = ap.parse_args()

    logging_setup.setup()
    init_db()
    log = logging.getLogger("calm_money.run")

    if args.list:
        _print_status()
        return 0

    import pipeline
    import store

    # --slot: force a single format immediately, keyed to its slot time today.
    if args.slot:
        slots = [s for s in _todays_slots() if s[0] == args.slot] or _todays_slots()
        fmt, local, sched_iso = next(s for s in slots if s[0] == args.slot)
        log.info("forced run: %s", fmt)
        res = pipeline.run_slot(fmt, sched_iso)
        if res.status == "failed":
            log.error("slot %s failed: %s", fmt, res.detail)
            return 1
        log.info("result: %s", res)
        return 0

    now_utc = datetime.now(pytz.utc)
    window = timedelta(hours=args.catchup_hours)

    due = []
    for fmt, local, sched_iso in _todays_slots():
        sched_utc = datetime.fromisoformat(sched_iso)
        if args.force or (sched_utc <= now_utc <= sched_utc + window):
            due.append((fmt, sched_iso, local))

    if not due:
        log.info("no slots due right now. Use --list to see today's schedule.")
        return 0

    exit_code = 0
    for fmt, sched_iso, local in due:
        log.info("running due slot: %s (scheduled %s ET)", fmt, local.strftime("%I:%M %p"))
        res = pipeline.run_slot(fmt, sched_iso)
        if res.status == "failed":
            log.error("slot %s failed: %s", fmt, res.detail)
            exit_code = 1
        else:
            log.info("result: %s", res)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
