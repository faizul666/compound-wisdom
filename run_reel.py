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


def _due_reel_slots():
    """Today's reel slots whose time has arrived, as (iso_utc, local), oldest first."""
    tz = pytz.timezone(config.TIMEZONE_TARGET)
    now_local = datetime.now(tz)
    now_utc = datetime.now(pytz.utc)
    out = []
    for h, m in config.REEL_SLOTS:
        local = tz.localize(datetime(now_local.year, now_local.month, now_local.day, h, m))
        iso = local.astimezone(pytz.utc).isoformat()
        if datetime.fromisoformat(iso) <= now_utc:
            out.append((iso, local))
    out.sort(key=lambda x: x[0])
    return out


def _pick_music() -> "object | None":
    if not config.MUSIC_DIR.exists():
        return None
    tracks = [p for p in config.MUSIC_DIR.glob("*.mp3")] + [p for p in config.MUSIC_DIR.glob("*.m4a")]
    return random.choice(tracks) if tracks else None


_BANNED_BROLL = (
    "man in suit", "walking through city", "journaling", "hands on laptop",
    "typing on laptop", "city timelapse", "staring at sunset", "sunset over",
    "woman looking out",
)


def _clean_keywords(kws: list[str]) -> list[str]:
    """Drop cliche AI-slop b-roll terms; keep the concrete ones."""
    kept = [k for k in kws if not any(b in k.lower() for b in _BANNED_BROLL)]
    return kept or kws


def _caption(script) -> str:
    tags = " ".join("#" + h.strip().lstrip("#").replace(" ", "") for h in script.hashtags[:5])
    src = f"\n\nSource: {script.source_note}" if getattr(script, "source_note", "") else ""
    return f"{script.caption}{src}\n\n{tags}"


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

        due = [(iso, loc) for iso, loc in _due_reel_slots() if not store.reel_already_posted(iso)]
        if not due:
            log.info("no due-and-unposted reel slot right now; skipping.")
            return 0
        slot_iso, slot_local = due[0]  # oldest due slot, one per run
        log.info("making reel for slot %s ET", slot_local.strftime("%I:%M %p"))

        from reels import assemble, broll, publish, script, voice
        from reels.script import GenerationError, TransientError

        # Rotate away from recently-used themes, and tell the model the recent
        # hooks so it doesn't repeat an idea days later.
        recent_themes = store.recent_reel_themes(3)
        reel_wells = [w for w in config.WELLS if w != "book_lessons"]
        choices = [w for w in reel_wells if w not in recent_themes[:2]] or reel_wells
        chosen_theme = random.choice(choices)
        avoid_hooks = store.recent_reel_hooks(30)

        try:
            theme, spec = script.generate(theme=chosen_theme, avoid_hooks=avoid_hooks)
        except TransientError as e:
            log.warning("transient error generating reel script; will retry next run: %s", e)
            return 0
        except GenerationError as e:
            log.error("reel script generation failed: %s", e)
            return 1
        log.info("reel theme=%s hook=%r (avoiding %d recent)", theme, spec.hook_text, len(avoid_hooks))

        reel_dir = config.REELS_DIR
        clips_dir = reel_dir / "clips"
        if clips_dir.exists():
            shutil.rmtree(clips_dir, ignore_errors=True)
        reel_dir.mkdir(parents=True, exist_ok=True)

        vo_path = reel_dir / "vo.mp3"
        words, spans = voice.synthesize_beats(spec.beats(), vo_path)
        need = words[-1].end if words else config.REEL_TARGET_SECONDS
        hook_span = spans[0]
        stat_span = spans[1] if len(spans) > 1 else None  # the evidence beat
        log.info("voiceover %.1fs, %d words, %d beats", need, len(words), len(spans))

        keywords = _clean_keywords(spec.broll_keywords)
        try:
            clips = broll.fetch_clips(keywords, clips_dir, need)
        except Exception as e:
            log.error("b-roll fetch failed: %s", e)
            return 1
        log.info("fetched %d b-roll clips", len(clips))

        music = _pick_music()
        ts = datetime.now(pytz.utc).strftime("%Y%m%d_%H%M%S")
        out = reel_dir / f"reel_{ts}.mp4"
        assemble.assemble(
            clips, vo_path, words, out,
            hook_text=spec.hook_text, hook_span=hook_span,
            stat_text=spec.key_stat, stat_span=stat_span, music_path=music,
        )
        log.info("assembled %s (%d KB)", out.name, out.stat().st_size // 1024)

        try:
            fb_id = publish.publish(out, _caption(spec))
        except Exception as e:
            log.error("reel publish failed: %s", e)
            return 1

        store.record_reel(slot_iso, theme, spec.hook_text, str(out), fb_id)
        if not args.keep:
            shutil.rmtree(clips_dir, ignore_errors=True)
        log.info("reel done -> %s", fb_id)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
