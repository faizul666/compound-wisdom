"""Compliance & voice gate — regex pre-filter then an LLM judge.

The regex pre-filter is cheap and deterministic: it catches banned phrases
(check 6), ticker symbols and explicit buy/sell instructions (check 1), and
dollar/percentage outcome promises (check 2) before spending a model call. The
LLM judge (Gemini flash-lite at temperature 0) applies all six checks,
including the subjective voice ones (4, 5).

The final verdict is the union: a post passes only if the pre-filter is clean
AND the judge passes. failed_checks merges both sources.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Union

from pydantic import ValidationError

import config
from generation.generator import _client  # reuse the same lazy Gemini client
from schemas import ComplianceResult, ListPost, MiniBlogPost, QuotePost

PostPayload = Union[QuotePost, MiniBlogPost, ListPost]


# --------------------------------------------------------------------------
# Text extraction
# --------------------------------------------------------------------------
def gather_text(payload: PostPayload) -> str:
    """Concatenate every human-readable field of a post into one string."""
    if isinstance(payload, QuotePost):
        return "\n".join([payload.quote_text, payload.caption_body, payload.closing_question])
    if isinstance(payload, MiniBlogPost):
        return "\n".join([payload.headline, payload.caption_body, payload.closing_question])
    if isinstance(payload, ListPost):
        parts = [payload.title, payload.intro_line, payload.closing_line]
        for item in payload.items:
            parts.append(item.name)
            parts.append(item.explanation)
        return "\n".join(parts)
    raise TypeError(f"Unknown payload type: {type(payload)!r}")


# --------------------------------------------------------------------------
# Regex pre-filter
# --------------------------------------------------------------------------
# Patterns that imply specific investment advice (check 1).
_ADVICE_PATTERNS = [
    re.compile(r"\$[A-Z]{1,5}\b"),                       # tickers like $AAPL
    re.compile(r"\b(?:buy|sell|short)\s+(?:now|today|this)\b", re.I),
]
# Patterns that promise a reader outcome in dollars/percent (check 2).
# Educational illustrations ("$50 a month ... becomes roughly $60,000") are NOT
# matched here; only direct second-person promises are.
_OUTCOME_PATTERNS = [
    re.compile(r"\b(?:you(?:'ll| will)|guaranteed to)\s+(?:make|earn|have|get)\s+\$?\d", re.I),
    re.compile(r"\b(?:double|triple|10x|grow)\s+your\s+money\b", re.I),
    re.compile(r"\bguarantee(?:d|s)?\b", re.I),
]


def regex_prefilter(text: str) -> list[str]:
    """Return the list of failed check numbers found by cheap regex rules.

    Maps to: '6' banned phrases, '1' advice/tickers, '2' outcome promises.
    """
    lowered = text.lower()
    failed: set[str] = set()

    for phrase in config.BANNED_PHRASES:
        if phrase.lower() in lowered:
            failed.add("6")

    for pat in _ADVICE_PATTERNS:
        if pat.search(text):
            failed.add("1")

    for pat in _OUTCOME_PATTERNS:
        if pat.search(text):
            failed.add("2")

    return sorted(failed)


# --------------------------------------------------------------------------
# LLM judge
# --------------------------------------------------------------------------
@lru_cache(maxsize=None)
def _read_prompt(name: str) -> str:
    return (config.PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


def _judge_system_instruction() -> str:
    return "\n\n".join([_read_prompt("brand_voice.txt"), _read_prompt("system_judge.txt")])


def judge(payload: PostPayload) -> ComplianceResult:
    """Run the deterministic LLM judge. Raises on API/parse failure."""
    from google.genai import types

    post_json = json.dumps(payload.model_dump(), ensure_ascii=False, indent=2)
    cfg = types.GenerateContentConfig(
        system_instruction=_judge_system_instruction(),
        temperature=config.JUDGE_TEMPERATURE,
        max_output_tokens=1024,
        response_mime_type="application/json",
    )
    resp = _client().models.generate_content(
        model=config.MODEL_LITE,
        contents="Judge this post:\n\n" + post_json,
        config=cfg,
    )
    text = (getattr(resp, "text", None) or "").strip()
    if not text:
        raise RuntimeError("Judge returned empty response")
    try:
        data = json.loads(text)
        return ComplianceResult(**data)
    except (json.JSONDecodeError, ValidationError) as e:
        raise RuntimeError(f"Judge returned unparseable verdict: {e}; raw={text[:200]!r}") from e


# --------------------------------------------------------------------------
# Combined gate
# --------------------------------------------------------------------------
def check(payload: PostPayload) -> ComplianceResult:
    """Full gate: regex pre-filter unioned with the LLM judge.

    The judge is always consulted (it catches voice issues the regex can't),
    but a regex hit alone is enough to fail. If the judge call errors, we fail
    closed and record the error in notes — a post is never passed on a judge
    failure.
    """
    text = gather_text(payload)
    regex_failed = regex_prefilter(text)

    judge_failed: list[str] = []
    notes_parts: list[str] = []

    if not config.GEMINI_API_KEY:
        # Offline mode (no key): the LLM judge is intentionally unavailable, so
        # the verdict rests on the regex pre-filter only. This is a known dev/
        # DRY_RUN path, not a silent failure — note it explicitly.
        notes_parts.append("offline: regex pre-filter only (no GEMINI_API_KEY, judge skipped)")
        overall = not regex_failed
        return ComplianceResult(**{
            "pass": overall,
            "failed_checks": sorted(regex_failed, key=lambda x: (len(x), x)),
            "notes": (f"regex flagged checks {regex_failed} | " if regex_failed else "")
                     + notes_parts[0],
        })

    judge_pass = False
    try:
        verdict = judge(payload)
        judge_pass = verdict.pass_
        judge_failed = verdict.failed_checks
        if verdict.notes:
            notes_parts.append(f"judge: {verdict.notes}")
    except Exception as e:
        notes_parts.append(f"judge error (failed closed): {e}")

    all_failed = sorted(set(regex_failed) | set(judge_failed), key=lambda x: (len(x), x))
    if regex_failed:
        notes_parts.insert(0, f"regex pre-filter flagged checks {regex_failed}")

    overall = (not regex_failed) and judge_pass
    return ComplianceResult(
        **{
            "pass": overall,
            "failed_checks": all_failed,
            "notes": " | ".join(notes_parts) or "clean",
        }
    )
