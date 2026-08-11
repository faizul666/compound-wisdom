"""Single-slot pipeline: turn one due slot into one published post.

    brief -> generate -> compliance -> render image -> build caption
          -> record (ready) -> publish -> record (posted)

Idempotent per slot: if a post for the slot's exact scheduled time is already
marked posted, it is skipped. Compliance failures are not published — the
pipeline consumes that brief and tries the next available one, up to a cap.
"""
from __future__ import annotations

import logging

import captions
import config
import store
from generation import compliance, generator
from images import composer

log = logging.getLogger("calm_money.pipeline")

MAX_BRIEF_ATTEMPTS = 4


class SlotResult:
    def __init__(self, status: str, detail: str, post_id: int | None = None, fb_id: str | None = None):
        self.status = status      # posted | skipped | failed
        self.detail = detail
        self.post_id = post_id
        self.fb_id = fb_id

    def __str__(self) -> str:
        return f"{self.status}: {self.detail}"


def run_slot(format_type: str, scheduled_at_iso: str) -> SlotResult:
    if store.slot_already_posted(scheduled_at_iso):
        return SlotResult("skipped", f"slot {scheduled_at_iso} already posted")

    allow_fallback = not config.GEMINI_API_KEY  # offline writer only when no key

    chosen = None
    for attempt in range(1, MAX_BRIEF_ATTEMPTS + 1):
        brief = store.next_available_brief(format_type)
        if brief is None:
            return SlotResult("failed", f"no available briefs for format '{format_type}' "
                                        f"(reseed with: python seed_briefs.py)")
        brief_id = store.brief_row_id(brief)
        try:
            fmt, payload = generator.generate(brief, allow_fallback=allow_fallback)
            verdict = compliance.check(payload)
        except generator.TransientError as e:
            # API outage / network blip in generation OR the judge: keep the
            # brief and stop — retrying more briefs would just burn them. The
            # next scheduled (or catch-up) run retries this slot intact.
            log.warning("transient API error; brief %s preserved, aborting slot: %s", brief_id, e)
            return SlotResult("failed", f"transient API error (will retry next run): {e}")
        except generator.GenerationError as e:
            log.warning("generation failed (brief %s): %s", brief_id, e)
            store.mark_brief_used(brief_id)  # consume so we advance
            continue

        if not verdict.pass_:
            log.info("compliance rejected brief %s (checks %s): %s",
                     brief_id, verdict.failed_checks, verdict.notes)
            store.mark_brief_used(brief_id)
            continue

        chosen = (brief_id, payload, brief.well_id)
        break

    if chosen is None:
        return SlotResult("failed", f"no compliant post after {MAX_BRIEF_ATTEMPTS} attempts")

    brief_id, payload, well_id = chosen

    # render + caption + alt text
    image_path = composer.render(payload, well_id)
    caption = captions.build(payload)
    alt = captions.alt_text(payload)

    # record as ready, then publish
    post_id = store.insert_post(
        brief_id=brief_id,
        format_type=format_type,
        content_json=payload.model_dump_json(),
        image_path=str(image_path),
        scheduled_at_iso=scheduled_at_iso,
    )

    try:
        from publishing import publisher
        fb_id = publisher.publish(image_path, caption, alt_text=alt)
    except Exception as e:
        store.mark_post_failed(post_id, str(e))
        log.warning("publish failed for post %s: %s", post_id, e)  # run_due emits the ERROR/alert
        return SlotResult("failed", f"publish error: {e}", post_id=post_id)

    store.mark_post_posted(post_id, fb_id)
    store.mark_brief_used(brief_id)
    return SlotResult("posted", f"{format_type} -> {fb_id}", post_id=post_id, fb_id=fb_id)
