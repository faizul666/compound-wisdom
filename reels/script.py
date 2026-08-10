"""Generate a value/outcome reel script with Gemini.

Book-agnostic on purpose: the ideas can come from great books, but the reel
NEVER names a book or author — it delivers the value directly. Returns a
ReelScript (hook, spoken voiceover, b-roll keywords, caption, hashtags).
"""
from __future__ import annotations

import random
import time

import config
from generation.generator import (
    GENERATION_RETRIES,
    GenerationError,
    TransientError,
    _client,
    _is_transient,
)
from schemas import ReelScript

REEL_SYSTEM = """You write short-form vertical video scripts (Reels) for Compound Wisdom.
Each reel delivers ONE piece of genuinely useful, outcome-oriented advice that a
viewer can act on. You inherit the brand voice specification in full.

Hard rules:
- NEVER mention a book, an author, "in this book", or "studies show". Deliver the
  value directly, as if from a sharp mentor.
- The FIRST sentence is a scroll-stopping hook: a bold claim, a sharp question, or
  a "most people get this wrong" opener. It must work in the first 3 seconds.
- Structure the voiceover as: hook -> 3 tight, concrete value beats -> a short
  payoff or call to reflect. ~90-130 spoken words total.
- Plain spoken sentences only. No emojis, no numbered lists, no stage directions,
  no hashtags inside the voiceover.
- Outcome framing: connect the advice to a result the viewer wants.
- broll_keywords: 4-6 concrete, filmable visual terms (e.g. "person running at
  sunrise", "coffee morning routine", "city commute", "writing in notebook").
- caption: a punchy hook line, one or two lines of value, then a soft CTA
  (e.g. "Save this for later.").
- hashtags: 6-10 broad self-improvement tags without the # sign.

Return ONLY the ReelScript object."""


def _system_instruction() -> str:
    brand = (config.PROMPTS_DIR / "brand_voice.txt").read_text(encoding="utf-8").strip()
    return brand + "\n\n" + REEL_SYSTEM


def generate(theme: str | None = None) -> tuple[str, ReelScript]:
    """Generate a reel script for a theme (a well). Returns (theme, ReelScript)."""
    config.require("GEMINI_API_KEY")
    from google.genai import types

    if theme is None:
        theme = random.choice(list(config.WELLS))
    theme_desc = config.WELLS.get(theme, theme)

    cfg = types.GenerateContentConfig(
        system_instruction=_system_instruction(),
        temperature=0.95,
        max_output_tokens=2048,
        response_mime_type="application/json",
        response_schema=ReelScript,
    )
    prompt = (
        f"Write one value reel in the theme of {theme} ({theme_desc}). "
        "Pick a single specific, useful idea and make it outcome-oriented. "
        "Remember: never mention a book or author."
    )

    for attempt in range(1, GENERATION_RETRIES + 1):
        try:
            resp = _client().models.generate_content(
                model=config.MODEL_FLASH, contents=prompt, config=cfg
            )
            break
        except Exception as e:
            if _is_transient(str(e)):
                if attempt < GENERATION_RETRIES:
                    time.sleep(2 ** attempt)
                    continue
                raise TransientError(f"reel script transient error after {attempt}: {e}") from e
            raise GenerationError(f"reel script generation failed: {e}") from e

    parsed = getattr(resp, "parsed", None)
    if isinstance(parsed, ReelScript):
        script = parsed
    else:
        text = (getattr(resp, "text", None) or "").strip()
        if not text:
            raise GenerationError("reel script: empty model response")
        script = ReelScript.model_validate_json(text)

    if len(script.voiceover.split()) < 30:
        raise GenerationError("reel script: voiceover too short")
    return theme, script
