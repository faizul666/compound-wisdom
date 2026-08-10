"""Entry point: create and publish the daily value reel.

    research theme -> script -> voiceover -> b-roll -> assemble -> publish

One reel per day (idempotent on the day's reel slot). Fully autonomous. Respects
DRY_RUN (writes the .mp4 locally) and the kill switch. Run by reel.bat on a
daily Task Scheduler trigger.

    python run_reel.py            # make + publish today's reel
    python run_reel.py --keep     # keep intermediate clips/vo for inspection
"""
from __future__ import annotations

import argparse
import logging
import random
import shutil
from datetime import datetime

import pytz

import config
import logging_setup
import store
from db import init_db
from lock import single_instance


def _reel_slot_iso() -> str:
    tz = pytz.timezone(config.TIMEZONE_TARGET)
    now = datetime.now(tz)
    h, m = config.REEL_SLOT
    local = tz.localize(datetime(now.year, now.month, now.day, h, m))
    return local.astimezone(pytz.utc).isoformat()


def _pick_music() -> "object | None":
    if not config.MUSIC_DIR.exists():
        return None
    tracks = [p for p in config.MUSIC_DIR.glob("*.mp3")] + [p for p in config.MUSIC_DIR.glob("*.m4a")]
    return random.choice(tracks) if tracks else None


def _caption(script) -> str:
    tags = " ".join("#" + h.lstrip("#") for h in script.hashtags)
    return f"{script.caption}\n\n{tags}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Create and publish the daily reel.")
    ap.add_argument("--keep", action="store_true", help="Keep intermediate files.")
    args = ap.parse_args()

    logging_setup.setup()
    init_db()
    log = logging.getLogger("calm_money.reel")

    with single_instance("reel") as acquired:
        if not acquired:
            log.info("another reel run is in progress; skipping.")
            return 0

        slot_iso = _reel_slot_iso()
        if store.reel_already_posted(slot_iso):
            log.info("today's reel already posted; skipping.")
            return 0

        from reels import assemble, broll, publish, script, voice
        from reels.script import GenerationError, TransientError

        try:
            theme, spec = script.generate()
        except TransientError as e:
            log.warning("transient error generating reel script; will retry next run: %s", e)
            return 0
        except GenerationError as e:
            log.error("reel script generation failed: %s", e)
            return 1
        log.info("reel theme=%s hook=%r", theme, spec.hook_text)

        reel_dir = config.REELS_DIR
        clips_dir = reel_dir / "clips"
        if clips_dir.exists():
            shutil.rmtree(clips_dir, ignore_errors=True)
        reel_dir.mkdir(parents=True, exist_ok=True)

        vo_path = reel_dir / "vo.mp3"
        words = voice.synthesize(spec.voiceover, vo_path)
        need = words[-1].end if words else config.REEL_TARGET_SECONDS
        log.info("voiceover %.1fs, %d words", need, len(words))

        try:
            clips = broll.fetch_clips(spec.broll_keywords, clips_dir, need)
        except Exception as e:
            log.error("b-roll fetch failed: %s", e)
            return 1
        log.info("fetched %d b-roll clips", len(clips))

        music = _pick_music()
        ts = datetime.now(pytz.utc).strftime("%Y%m%d_%H%M%S")
        out = reel_dir / f"reel_{ts}.mp4"
        assemble.assemble(clips, vo_path, words, spec.hook_text, out, music)
        log.info("assembled %s (%d KB)", out.name, out.stat().st_size // 1024)

        try:
            fb_id = publish.publish(out, _caption(spec))
        except Exception as e:
            log.error("reel publish failed: %s", e)
            return 1

        store.record_reel(slot_iso, theme, str(out), fb_id)
        if not args.keep:
            shutil.rmtree(clips_dir, ignore_errors=True)
        log.info("reel done -> %s", fb_id)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
