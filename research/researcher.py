"""Research layer — generate topic briefs with Gemini + Google Search grounding.

Grounding and structured output (`response_schema`) are mutually exclusive in
the Gemini API, so this asks the model to emit raw JSON and parses it by hand,
then validates against ResearchBriefBatch. Newly produced briefs are de-duped
against the last N days of titles and inserted into the queue as 'available'.

On the free tier, grounding may be unavailable; set RESEARCH_USE_GROUNDING=0 to
skip it, and the layer also auto-falls-back to an ungrounded call if a grounded
call fails. Ungrounded briefs rely on the model's own knowledge — their source
URLs should be treated with more suspicion (run with --verify).
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache

from pydantic import ValidationError

import config
import store
from schemas import ResearchBrief

log = logging.getLogger("calm_money.research")


class ResearchError(RuntimeError):
    pass


@lru_cache(maxsize=None)
def _read_prompt(name: str) -> str:
    return (config.PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def _client():
    # Cached so the Client object stays referenced for the life of the process.
    # An uncached `_client().models.generate_content(...)` lets the temporary
    # Client get garbage-collected mid-request, which closes its transport and
    # raises "Cannot send a request, as the client has been closed."
    config.require("GEMINI_API_KEY")
    from google import genai
    return genai.Client(api_key=config.GEMINI_API_KEY)


def _build_prompt(n: int, avoid_titles: list[str]) -> str:
    import random

    import books

    examples = _read_prompt("examples_research.json")
    avoid = "\n".join(f"- {t}" for t in avoid_titles) or "(none yet)"
    sample = random.sample(books.all_books(), min(16, len(books.all_books())))
    book_list = "\n".join(f"- {t} by {a}" for t, a in sample)
    return "\n\n".join([
        _read_prompt("system_research.txt"),
        "Example briefs (shape and quality):",
        examples,
        "Candidate books to draw from — prefer these, vary across them, use exact titles:",
        book_list,
        "Recently used angle titles to AVOID (no repeats or near-duplicates):",
        avoid,
        f"Produce {n} new, distinct briefs.\n"
        f"well_id MUST be EXACTLY one of: {', '.join(config.WELL_IDS)} (do not invent well ids).\n"
        "suggested_format MUST be EXACTLY one of: quote, mini_blog, list, book_summary.\n"
        "For a book_summary brief: well_id must be 'book_lessons', and you MUST set "
        "book_title and book_author to a real book (prefer the candidate list).\n"
        "suggested_list_count is 5 or 10 only when suggested_format is list, else null.\n"
        "FORMAT MIX: aim for a balanced spread — roughly equal numbers of "
        "book_summary, list, quote, and mini_blog.\n"
        'Return ONLY the JSON object: {"briefs": [ ... ]}.',
    ])


def _generate_text(prompt: str, use_grounding: bool) -> str:
    from google.genai import types
    kwargs = dict(
        system_instruction=_read_prompt("brand_voice.txt"),
        temperature=0.9,
        max_output_tokens=config.MAX_OUTPUT_TOKENS,
    )
    if use_grounding:
        kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]
    else:
        # only safe to request strict JSON mime when NOT grounding
        kwargs["response_mime_type"] = "application/json"

    from generation.generator import GENERATION_RETRIES, _is_transient

    resp = None
    for attempt in range(1, GENERATION_RETRIES + 1):
        try:
            resp = _client().models.generate_content(
                model=config.MODEL_FLASH,
                contents=prompt,
                config=types.GenerateContentConfig(**kwargs),
            )
            break
        except Exception as e:
            if _is_transient(str(e)) and attempt < GENERATION_RETRIES:
                import time
                time.sleep(2 ** attempt)
                continue
            raise
    text = (getattr(resp, "text", None) or "").strip()
    if not text:
        finish = None
        try:
            finish = resp.candidates[0].finish_reason
        except Exception:
            pass
        raise ResearchError(f"empty research response (finish_reason={finish})")
    return text


def _extract_json(text: str) -> dict:
    """Tolerant JSON extraction — strips ``` fences and surrounding prose."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
    # fall back to the outermost braces
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start:end + 1]
    try:
        return json.loads(t)
    except json.JSONDecodeError as e:
        raise ResearchError(f"could not parse JSON from research output: {e}") from e


def generate_briefs(n: int | None = None) -> list[ResearchBrief]:
    """Call Gemini and return validated, de-duplicated briefs (not yet stored)."""
    n = n or config.RESEARCH_BRIEFS_PER_RUN
    avoid = store.recent_brief_titles(config.RESEARCH_DEDUP_DAYS)
    prompt = _build_prompt(n, avoid)

    want_grounding = config.RESEARCH_USE_GROUNDING
    try:
        text = _generate_text(prompt, use_grounding=want_grounding)
    except Exception as e:
        if want_grounding:
            log.warning("grounded research failed (%s); retrying ungrounded", e)
            text = _generate_text(prompt, use_grounding=False)
        else:
            raise

    data = _extract_json(text)
    raw_briefs = data.get("briefs", []) if isinstance(data, dict) else []
    if not raw_briefs:
        raise ResearchError("research output had no 'briefs' array")

    # Validate each brief independently — keep the good ones, drop malformed
    # ones (e.g. an invented well_id) rather than failing the whole batch.
    validated: list[ResearchBrief] = []
    dropped = 0
    for rb in raw_briefs:
        try:
            validated.append(ResearchBrief.model_validate(rb))
        except ValidationError:
            dropped += 1
    if dropped:
        log.warning("dropped %d malformed brief(s) from research output", dropped)
    if not validated:
        raise ResearchError("no valid briefs in research output")

    # de-dup against recent titles (case-insensitive) and within the batch
    seen = {t.strip().lower() for t in avoid}
    unique: list[ResearchBrief] = []
    for b in validated:
        key = b.angle_title.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(b)
    return unique


def run(n: int | None = None) -> int:
    """Generate briefs and insert the new ones. Returns count inserted."""
    briefs = generate_briefs(n)
    inserted = store.seed_briefs(briefs)
    log.info("research produced %d briefs, inserted %d new", len(briefs), inserted)
    return inserted
