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
from functools import lru_cache
from typing import Type, Union

from pydantic import BaseModel, ValidationError

import config
from schemas import ListPost, MiniBlogPost, QuotePost, ResearchBrief

PostPayload = Union[QuotePost, MiniBlogPost, ListPost]


class GenerationError(RuntimeError):
    """Raised when generation fails or returns content that won't validate."""


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

    try:
        resp = _client().models.generate_content(
            model=_model_for(format_type),
            contents=_user_content(format_type, brief),
            config=cfg,
        )
    except Exception as e:  # network, quota, API errors
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
        if len(payload.items) != payload.count:
            raise GenerationError(
                f"list: count={payload.count} but {len(payload.items)} items returned"
            )


# --------------------------------------------------------------------------
# Offline fallback writer (no LLM) — deterministic, compliance-safe
# --------------------------------------------------------------------------
from schemas import ListItem  # noqa: E402  (local to the fallback path)

# A small pool of calm, on-brand, banned-phrase-free list items the fallback
# slices to satisfy a list's count. Kept generic on purpose.
_FALLBACK_LIST_ITEMS = [
    ("Automate saving before you see the money", "Money you never see in checking rarely feels available to spend."),
    ("Wait a day on non-essential buys", "Most impulse urges fade within a day, doing the filtering for free."),
    ("Save part of every raise first", "Lifestyle creep eats raises by default unless some is set aside first."),
    ("Keep a working car a few extra years", "The gap between a paid-off car and a new payment compounds quietly."),
    ("Review subscriptions each quarter", "A short review four times a year returns more than most expect."),
    ("Cook at home a few nights a week", "It is a default, not a rule of perfection."),
    ("Track net worth quarterly, not daily", "Quarterly checking shows the slope without the daily anxiety."),
    ("Buy quality once for things used often", "For shoes, tools, and daily items the math favors buying well once."),
    ("Picture your future self before big buys", "Imagine opening next year's statement before you decide today."),
    ("Notice when a new normal is installed", "Lifestyle rises one reasonable upgrade at a time unless you watch."),
]


def _fallback_generate(brief: ResearchBrief) -> PostPayload:
    """Build a structurally valid post from the brief without calling an LLM."""
    summary = brief.angle_summary.strip()
    fact = brief.supporting_facts[0].fact if brief.supporting_facts else ""

    if brief.suggested_format == "quote":
        return QuotePost(
            quote_text=brief.angle_title.strip().rstrip(".") + ".",
            attribution="— Calm Money Daily",
            image_background_template="serif_card",
            caption_body=(
                f"{summary}\n\n{fact}\n\n"
                "The calm approach is not about doing more. It is about noticing "
                "the quiet choices that shape a financial life over years."
            ),
            closing_question="When did you last feel calm about a money decision, and why?",
        )

    if brief.suggested_format == "mini_blog":
        return MiniBlogPost(
            headline=brief.angle_title.strip(),
            headline_image_template="editorial_serif",
            caption_body=(
                f"{summary}\n\n{fact}\n\n"
                "None of this asks for urgency. It asks for patience, repeated "
                "quietly, for long enough that the small choices add up.\n\n"
                "That is the whole idea: a calmer relationship with money, built "
                "one unremarkable decision at a time."
            ),
            closing_question="What is one small money habit you have kept longer than you expected?",
        )

    # list
    count = brief.suggested_list_count or 5
    items = [ListItem(name=n, explanation=e) for n, e in _FALLBACK_LIST_ITEMS[:count]]
    title = brief.angle_title.strip()
    if not title[:2].strip().isdigit():
        title = f"{count} {title}"
    return ListPost(
        title=title,
        count=count,  # type: ignore[arg-type]
        list_image_template="warm_gradient_list",
        intro_line="These are small, repeatable habits — gentler than they look, and powerful over time.",
        items=items,
        closing_line="None of these change a year. All of them change a decade.",
    )
