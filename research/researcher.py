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
from schemas import ResearchBrief, ResearchBriefBatch

log = logging.getLogger("calm_money.research")


class ResearchError(RuntimeError):
    pass


@lru_cache(maxsize=None)
def _read_prompt(name: str) -> str:
    return (config.PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


def _client():
    config.require("GEMINI_API_KEY")
    from google import genai
    return genai.Client(api_key=config.GEMINI_API_KEY)


def _build_prompt(n: int, avoid_titles: list[str]) -> str:
    examples = _read_prompt("examples_research.json")
    avoid = "\n".join(f"- {t}" for t in avoid_titles) or "(none yet)"
    return "\n\n".join([
        _read_prompt("system_research.txt"),
        "Here is an example brief showing the expected shape and quality:",
        examples,
        "Recently used angle titles to AVOID duplicating (do not repeat or "
        "near-duplicate any of these):",
        avoid,
        f"Produce {n} new, distinct briefs spread across multiple wells. "
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

    resp = _client().models.generate_content(
        model=config.MODEL_FLASH,
        contents=prompt,
        config=types.GenerateContentConfig(**kwargs),
    )
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
    try:
        batch = ResearchBriefBatch.model_validate(data)
    except ValidationError as e:
        raise ResearchError(f"research output failed schema validation: {e}") from e

    # de-dup against recent titles (case-insensitive) and within the batch
    seen = {t.strip().lower() for t in avoid}
    unique: list[ResearchBrief] = []
    for b in batch.briefs:
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
