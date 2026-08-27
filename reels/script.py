"""Generate a value reel script with Gemini + Google Search grounding.

Grounding matters here: the reel's edge over faceless AI pages is that it cites a
REAL name, number, and year (with a caveat) instead of "studies show". Grounding
and response_schema are mutually exclusive, so we prompt for raw JSON and parse
it into a ReelScript. Book-agnostic framing (never "in this book"), but naming
the underlying researcher/thinker is encouraged.
"""
from __future__ import annotations

import logging
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
from research.researcher import _extract_json
from schemas import ReelScript

log = logging.getLogger("calm_money.reels.script")

REEL_SYSTEM = """You write short vertical video scripts (Reels) for a broad
self-improvement audience. Each reel delivers ONE genuinely useful, surprising
idea backed by a real, specific piece of research. You inherit the brand voice.

NON-NEGOTIABLE RULES:

1. NAME THE THING IN THE HOOK. The claim itself is the hook. Never withhold the
   subject with "this", "the secret", "the one thing", "do this", "the question".
   BAD: "The question that kills bad decisions." GOOD: "Munger never asked how to
   succeed. He asked how to guarantee failure, then avoided that."

2. MAKE THE RESEARCH VISIBLE. Every reel must contain at least one real name,
   number, and year that a lazy competitor wouldn't look up. Say who, how many,
   what year. Include a caveat if the finding is limited ("only replicated a few
   times") — the caveat builds trust and drives comments. Do NOT fabricate: use
   only real, verifiable specifics. Never mention a book title or "in this book".

2b. ORIGINAL WORDS ONLY. The idea may come from a book, but express it entirely
   in your own original phrasing. Never reproduce a book's exact wording, its
   famous one-liner, or its sentence structure — reframe the idea so it reads as
   your own insight, not a copied quote. (Naming a real researcher or study with
   a number and year is a fact and is allowed; lifting an author's memorable line
   is not.)

3. FIVE BEATS, ~25-30 seconds total, spoken plainly (no emojis, no lists). Keep
   each beat TIGHT — respect the word caps:
   - hook_claim (<=12 words): the concrete claim, no setup. Start on a number or
     hard word, never "So" or "The".
   - evidence (<=22 words): the real name + number + year (+ caveat).
   - mechanism (<=38 words): WHY it's true. The meat — but say it in ONE sharp
     idea, not three. Most reels are empty here; you are not, but stay brief.
   - action (<=24 words): one specific thing to do tomorrow, as a plain sentence.
   - question (<=14 words): a BINARY, answerable question that invites a comment
     ("Which one are you?", "Car or house — which got you?"). Not "follow for more".

4. key_stat: the single number or name to flash big on screen (e.g. "66 DAYS").
5. source_note: the citation, e.g. "Lally, University College London, 2009".
6. broll_keywords: 5-8 CONCRETE nouns that literally illustrate the words/numbers
   (e.g. "calendar pages flipping", "stack of coins", "runner tying shoes"). BANNED
   (they are the visual signature of AI slop): "man in suit walking through city",
   "woman journaling by a window", "hands typing on laptop", "city timelapse",
   "person staring at sunset".

Return ONLY a JSON object with keys: hook_text, hook_claim, evidence, mechanism,
action, question, key_stat, source_note, broll_keywords, caption, hashtags.
No markdown fences, no commentary."""


def _system_instruction() -> str:
    brand = (config.PROMPTS_DIR / "brand_voice.txt").read_text(encoding="utf-8").strip()
    return brand + "\n\n" + REEL_SYSTEM


def _call(prompt: str, use_grounding: bool) -> str:
    from google.genai import types

    kwargs = dict(system_instruction=_system_instruction(), temperature=0.9,
                  max_output_tokens=2048)
    if use_grounding:
        kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]
    else:
        kwargs["response_mime_type"] = "application/json"

    for attempt in range(1, GENERATION_RETRIES + 1):
        try:
            resp = _client().models.generate_content(
                model=config.MODEL_FLASH, contents=prompt,
                config=types.GenerateContentConfig(**kwargs),
            )
            break
        except Exception as e:
            if _is_transient(str(e)):
                if attempt < GENERATION_RETRIES:
                    time.sleep(2 ** attempt)
                    continue
                raise TransientError(f"reel script transient error after {attempt}: {e}") from e
            raise GenerationError(f"reel script generation failed: {e}") from e

    text = (getattr(resp, "text", None) or "").strip()
    if not text:
        raise GenerationError("reel script: empty model response")
    return text


def generate(theme: str | None = None, avoid_hooks: list[str] | None = None) -> tuple[str, ReelScript]:
    """Generate a reel script for a theme (a well). Returns (theme, ReelScript).

    avoid_hooks are recently-used reel hooks; the model is told to pick a
    genuinely different idea so reels don't repeat across days.
    """
    config.require("GEMINI_API_KEY")
    if theme is None:
        # Reels are book-agnostic, so exclude the book_lessons well.
        reel_wells = [w for w in config.WELLS if w != "book_lessons"]
        theme = random.choice(reel_wells)
    theme_desc = config.WELLS.get(theme, theme)

    avoid = "\n".join(f"- {h}" for h in (avoid_hooks or [])[:40]) or "(none yet)"
    prompt = (
        f"Write ONE value reel in the theme of {theme} ({theme_desc}). "
        "Pick a single specific, surprising idea and find a REAL study or thinker "
        "with a name, number, and year to anchor it. Follow the five-beat structure.\n\n"
        "Do NOT repeat, reuse, or paraphrase any of these recently-used reel ideas — "
        "choose a genuinely different idea AND a different study/thinker:\n" + avoid
    )

    # Try grounded first (real citations). If the grounded call fails OR returns
    # malformed JSON, fall back to a structured (response_schema) ungrounded call,
    # which is guaranteed to be valid JSON. TransientError still propagates.
    script = None
    if config.RESEARCH_USE_GROUNDING:
        try:
            script = _parse_reel(_call(prompt, use_grounding=True))
        except TransientError:
            raise
        except Exception as e:
            log.warning("grounded reel generation failed (%s); using structured fallback", e)
    if script is None:
        script = _call_structured(prompt)

    if len((script.mechanism + " " + script.hook_claim).split()) < 15:
        raise GenerationError("reel script: too thin")
    return theme, script


def _parse_reel(text: str) -> ReelScript:
    return ReelScript.model_validate(_extract_json(text))


def _call_structured(prompt: str) -> ReelScript:
    """Ungrounded call with response_schema — guaranteed valid ReelScript JSON."""
    from google.genai import types

    cfg = types.GenerateContentConfig(
        system_instruction=_system_instruction(), temperature=0.9,
        max_output_tokens=2048, response_mime_type="application/json",
        response_schema=ReelScript,
    )
    from pydantic import ValidationError

    last_err = "no attempt"
    for attempt in range(1, GENERATION_RETRIES + 1):
        try:
            resp = _client().models.generate_content(
                model=config.MODEL_FLASH, contents=prompt, config=cfg)
        except Exception as e:
            if _is_transient(str(e)):
                if attempt < GENERATION_RETRIES:
                    time.sleep(2 ** attempt)
                    continue
                raise TransientError(f"reel structured transient error: {e}") from e
            raise GenerationError(f"reel structured generation failed: {e}") from e

        # Parse INSIDE the loop: an empty/invalid response is retried, not fatal.
        parsed = getattr(resp, "parsed", None)
        if isinstance(parsed, ReelScript):
            return parsed
        text = (getattr(resp, "text", None) or "").strip()
        if text:
            try:
                return ReelScript.model_validate_json(text)
            except ValidationError as e:
                last_err = f"validation: {e}"
        else:
            last_err = "empty response"
        if attempt < GENERATION_RETRIES:
            time.sleep(1)
    raise GenerationError(f"reel structured produced no valid script after retries ({last_err})")
