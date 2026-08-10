"""Content generators — turn a research brief into a finished, schema-valid post.

One generator per format, all sharing the brand voice + system generator prompt
and a set of few-shot examples loaded from prompts/. Generation uses Gemini
structured output (`response_schema`), so the returned object is already a
validated Pydantic model.

Quotes and lists run on flash; the mini-blog anchor runs on whatever
config.miniblog_model() resolves to (pro when allowed, flash on the free tier).

Nothing here publishes or crashes the pipeline on its own — callers decide how
to handle GenerationError.
"""
from __future__ import annotations

import json
import time
from functools import lru_cache
from typing import Type, Union

from pydantic import BaseModel, ValidationError

import config
from schemas import BookSummaryPost, ListPost, MiniBlogPost, QuotePost, ResearchBrief

PostPayload = Union[QuotePost, MiniBlogPost, ListPost, BookSummaryPost]


class GenerationError(RuntimeError):
    """Raised when generation fails or returns content that won't validate."""


class TransientError(GenerationError):
    """A retryable failure (API 503/429, network blip). The caller should NOT
    consume the brief — the same brief can be retried on the next run."""


GENERATION_RETRIES = 3
_TRANSIENT_MARKERS = (
    "503", "unavailable", "429", "resource_exhausted", "getaddrinfo",
    "timed out", "timeout", "deadline", "connection", "temporarily", "overloaded",
)


def _is_transient(msg: str) -> bool:
    m = msg.lower()
    return any(k in m for k in _TRANSIENT_MARKERS)


# --------------------------------------------------------------------------
# Prompt loading (cached — these are static files)
# --------------------------------------------------------------------------
@lru_cache(maxsize=None)
def _read_prompt(name: str) -> str:
    return (config.PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


@lru_cache(maxsize=None)
def _read_examples(name: str) -> str:
    """Return the example file pretty-printed as a compact JSON string for the prompt."""
    raw = json.loads((config.PROMPTS_DIR / name).read_text(encoding="utf-8"))
    return json.dumps(raw, ensure_ascii=False, indent=2)


# (format_type) -> (format_prompt_file, examples_file, schema, model_resolver)
_FORMATS: dict[str, tuple[str, str, Type[BaseModel]]] = {
    "quote": ("format_quote.txt", "examples_quote.json", QuotePost),
    "mini_blog": ("format_miniblog.txt", "examples_miniblog.json", MiniBlogPost),
    "list": ("format_list.txt", "examples_list.json", ListPost),
    "book_summary": ("format_book_summary.txt", "examples_book_summary.json", BookSummaryPost),
}


def _model_for(format_type: str) -> str:
    return config.miniblog_model() if format_type == "mini_blog" else config.MODEL_FLASH


@lru_cache(maxsize=1)
def _client():
    """Lazily build the Gemini client so importing this module needs no key."""
    config.require("GEMINI_API_KEY")
    from google import genai  # imported lazily to keep import-time deps light

    return genai.Client(api_key=config.GEMINI_API_KEY)


def _system_instruction(format_type: str) -> str:
    format_prompt = _read_prompt(_FORMATS[format_type][0])
    return "\n\n".join(
        [
            _read_prompt("brand_voice.txt"),
            _read_prompt("system_generator.txt"),
            format_prompt,
        ]
    )


def _user_content(format_type: str, brief: ResearchBrief) -> str:
    examples = _read_examples(_FORMATS[format_type][1])
    brief_json = json.dumps(brief.model_dump(), ensure_ascii=False, indent=2)
    parts = [
        "Here are examples of excellent posts in this exact format. Match their "
        "voice, cadence, and specificity — do not copy their content:",
        examples,
        "Now write ONE new post in this format, grounded in the following "
        "research brief. Use its supporting facts and voice_compatibility_notes, "
        "but write in the brand voice:",
        brief_json,
    ]
    return "\n\n".join(parts)


def generate(brief: ResearchBrief, *, allow_fallback: bool = False) -> tuple[str, PostPayload]:
    """Generate a post for `brief` in its suggested format.

    Returns (format_type, payload). Raises GenerationError on any failure.
    When no GEMINI_API_KEY is configured and allow_fallback is True, a
    deterministic non-LLM post is built from the brief instead (used for
    DRY_RUN / offline development). With a key present, generation is always
    via Gemini; API failures raise rather than silently degrading.
    """
    format_type = brief.suggested_format
    if format_type not in _FORMATS:
        raise GenerationError(f"Unknown format: {format_type!r}")

    if not config.GEMINI_API_KEY:
        if allow_fallback:
            return format_type, _fallback_generate(brief)
        raise GenerationError(
            "GEMINI_API_KEY not set. Set it in .env, or run with DRY_RUN to use "
            "the offline fallback writer."
        )

    _, _, schema = _FORMATS[format_type]
    from google.genai import types

    cfg = types.GenerateContentConfig(
        system_instruction=_system_instruction(format_type),
        temperature=config.GENERATION_TEMPERATURE,
        max_output_tokens=config.MAX_OUTPUT_TOKENS,
        response_mime_type="application/json",
        response_schema=schema,
    )

    resp = None
    for attempt in range(1, GENERATION_RETRIES + 1):
        try:
            resp = _client().models.generate_content(
                model=_model_for(format_type),
                contents=_user_content(format_type, brief),
                config=cfg,
            )
            break
        except Exception as e:  # network, quota, API errors
            if _is_transient(str(e)):
                if attempt < GENERATION_RETRIES:
                    time.sleep(2 ** attempt)  # 2s, 4s backoff
                    continue
                raise TransientError(
                    f"transient API error for {format_type} after {attempt} attempts: {e}"
                ) from e
            raise GenerationError(f"Gemini call failed for {format_type}: {e}") from e

    payload = _parse_response(resp, schema, format_type)
    _post_validate(format_type, payload, brief)
    return format_type, payload


def _parse_response(resp, schema: Type[BaseModel], format_type: str) -> PostPayload:
    """Prefer the SDK's parsed object; fall back to parsing resp.text ourselves."""
    parsed = getattr(resp, "parsed", None)
    if isinstance(parsed, schema):
        return parsed

    text = getattr(resp, "text", None)
    if not text:
        # A thinking model that hit the token cap returns no text — surface it.
        finish = None
        try:
            finish = resp.candidates[0].finish_reason
        except Exception:
            pass
        raise GenerationError(
            f"{format_type}: empty response from model (finish_reason={finish}). "
            "Likely truncated output."
        )
    try:
        return schema.model_validate_json(text)
    except ValidationError as e:
        raise GenerationError(f"{format_type}: response failed schema validation: {e}") from e


def _post_validate(format_type: str, payload: PostPayload, brief: ResearchBrief) -> None:
    """Structural checks the JSON schema can't express."""
    if isinstance(payload, ListPost):
        if payload.count not in (5, 7, 10):
            raise GenerationError(f"list: count={payload.count} must be 5, 7, or 10")
        if len(payload.items) != payload.count:
            raise GenerationError(
                f"list: count={payload.count} but {len(payload.items)} items returned"
            )
    if isinstance(payload, BookSummaryPost):
        if payload.count not in (5, 7):
            raise GenerationError(f"book_summary: count={payload.count} must be 5 or 7")
        if len(payload.lessons) != payload.count:
            raise GenerationError(
                f"book_summary: count={payload.count} but {len(payload.lessons)} lessons returned"
            )


# --------------------------------------------------------------------------
# Offline fallback writer (no LLM) — deterministic, compliance-safe
# --------------------------------------------------------------------------
from schemas import BookLesson, ListItem  # noqa: E402  (local to the fallback path)

# Generic, safe self-improvement items the fallback slices to fill a list.
_FALLBACK_LIST_ITEMS = [
    ("Systems beat goals", "You fall to the level of your systems, not the height of your goals. Design the routine."),
    ("Aim for 1% better", "Tiny gains feel invisible daily but compound to roughly 37x over a year."),
    ("Reduce friction", "Most habits fail on friction, not willpower. Make the good option the easy one."),
    ("Use inversion", "Ask how you'd fail, then avoid that. Munger built a fortune mostly by not being stupid."),
    ("Think second-order", "Ask 'and then what?' A cheap choice today can be expensive in six months."),
    ("Protect deep focus", "One undistracted hour beats a whole day of half-attention. Guard it."),
    ("Save without a reason", "Savings buys options and control over your time — the highest dividend money pays."),
    ("Never miss twice", "One missed day is an accident; two starts a new pattern. Bounce back fast."),
    ("Read 20 pages a day", "That's 20-30 books a year — more than most people read in a decade."),
    ("Leave a margin of safety", "Plans fail. Room for error is what keeps a bad year from ending the game."),
]

# Real, safe quote used by the keyless fallback (never fabricated).
_FALLBACK_QUOTE = (
    "You do not rise to the level of your goals. You fall to the level of your systems.",
    "— James Clear, Atomic Habits",
)


def _fallback_generate(brief: ResearchBrief) -> PostPayload:
    """Build a structurally valid post from the brief without calling an LLM."""
    summary = brief.angle_summary.strip()
    fact = brief.supporting_facts[0].fact if brief.supporting_facts else ""

    if brief.suggested_format == "quote":
        return QuotePost(
            quote_text=_FALLBACK_QUOTE[0],
            attribution=_FALLBACK_QUOTE[1],
            image_background_template="serif_card",
            caption_body=(
                f"{summary}\n\n{fact}\n\n"
                "The idea is simple: decide the system once, then let repetition do the work."
            ),
            closing_question="What's one system you set up once that still pays off today?",
        )

    if brief.suggested_format == "mini_blog":
        return MiniBlogPost(
            headline=brief.angle_title.strip(),
            headline_image_template="editorial_serif",
            caption_body=(
                f"{summary}\n\n{fact}\n\n"
                "The useful part isn't the big insight — it's the small, repeatable "
                "action you can take today and keep taking.\n\n"
                "That's how good ideas compound: quietly, undisturbed, for longer than feels exciting."
            ),
            closing_question="What's one idea from a book that actually changed how you act?",
        )

    if brief.suggested_format == "book_summary":
        count = 5
        title = brief.book_title or "Atomic Habits"
        author = brief.book_author or "James Clear"
        lessons = [BookLesson(lesson=n, detail=d) for n, d in _FALLBACK_LIST_ITEMS[:count]]
        return BookSummaryPost(
            book_title=title,
            book_author=author,
            count=count,
            headline=f"{count} lessons from {title}",
            book_image_template="cover_left",
            intro_line=summary or f"The core ideas from {title}, distilled.",
            lessons=lessons,
            closing_line="Pick one lesson and act on it today — that's how books actually change anything.",
        )

    # list
    count = brief.suggested_list_count or 5
    items = [ListItem(name=n, explanation=d) for n, d in _FALLBACK_LIST_ITEMS[:count]]
    title = brief.angle_title.strip()
    if not title[:2].strip().isdigit():
        title = f"{count} {title}"
    return ListPost(
        title=title,
        count=count,  # type: ignore[arg-type]
        list_image_template="numbered_bold",
        intro_line="A few ideas worth keeping — each one small enough to use this week.",
        items=items,
        closing_line="Boring, repeated, and undisturbed beats impressive and inconsistent.",
    )
