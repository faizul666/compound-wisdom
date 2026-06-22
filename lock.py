"""Single-instance lock so two runs can't act on the same slot at once.

Without this, a scheduled run.bat and a manual run_now.bat firing at the same
moment could both see a slot as unposted and both publish it (a duplicate).
The lock is advisory and OS-backed: it is released automatically when the
process exits, even on a crash, so it can't get stuck.

    with single_instance("post") as acquired:
        if not acquired:
            return  # another run holds it; do nothing
        ... do work ...
"""
from __future__ import annotations

import logging
from contextlib import contextmanager

import config

log = logging.getLogger("calm_money.lock")


@contextmanager
def single_instance(name: str):
    """Yield True if this process got the lock, False if another run holds it."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = config.DATA_DIR / f"{name}.lock"
    fh = open(lock_path, "a+")

    try:
        import msvcrt
        is_windows = True
    except ImportError:
        is_windows = False

    acquired = False
    try:
        try:
            if is_windows:
                import msvcrt
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            acquired = False  # another process holds the lock
        yield acquired
    finally:
        if acquired:
            try:
                if is_windows:
                    import msvcrt
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        fh.close()
