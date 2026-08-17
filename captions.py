"""Facebook caption + alt-text for each static post format.

Written search-first (line 1 is a searchable claim + entity, before the ~125-char
"See more" cut) AND mobile-readable: every block — hook, intro, each numbered
item, close, metadata — is separated by a blank line so nothing reads as a wall
of text on a phone. Captions and custom alt text are Google-indexed since July
2025, so both carry entity signals.
"""
from __future__ import annotations

import re
from typing import Union

from schemas import BookSummaryPost, ListPost, MiniBlogPost, QuotePost

PostPayload = Union[QuotePost, MiniBlogPost, ListPost, BookSummaryPost]
MAX_TAGS = 5


def _tags(hashtags: list[str]) -> str:
    seen, out = set(), []
    for h in hashtags:
        t = "#" + h.strip().lstrip("#").replace(" ", "")
        if len(t) > 1 and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
        if len(out) >= MAX_TAGS:
            break
    return " ".join(out)


def _paras(text: str) -> list[str]:
    """Split body prose into paragraphs (on blank lines), trimmed."""
    return [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]


def build(payload: PostPayload) -> str:
    """Assemble the caption. Every block is joined by a blank line."""
    if isinstance(payload, BookSummaryPost):
        blocks = [payload.caption_hook, payload.intro_line]
        blocks += [f"{i}. {l.lesson} — {l.detail}" for i, l in enumerate(payload.lessons, 1)]
        blocks += [payload.closing_line,
                   f"\U0001F4D6 {payload.book_title} by {payload.book_author} ({payload.publication_year})"]
    elif isinstance(payload, ListPost):
        blocks = [payload.caption_hook, payload.intro_line]
        blocks += [f"{i}. {item.name} — {item.explanation}" for i, item in enumerate(payload.items, 1)]
        blocks += [payload.closing_line]
    elif isinstance(payload, QuotePost):
        blocks = [f"“{payload.quote_text}”\n{payload.attribution}"]
        blocks += _paras(payload.caption_body)
        blocks += [payload.closing_question]
    elif isinstance(payload, MiniBlogPost):
        blocks = [payload.caption_hook]
        blocks += _paras(payload.caption_body)
        blocks += [payload.closing_question]
    else:
        raise TypeError(f"Unknown payload type: {type(payload)!r}")

    body = "\n\n".join(b for b in blocks if b and b.strip())
    return f"{body}\n\n{_tags(payload.hashtags)}"


def alt_text(payload: PostPayload) -> str:
    """A plain-English sentence with the searchable entities (for alt_text_custom)."""
    if isinstance(payload, BookSummaryPost):
        names = ", ".join(l.lesson for l in payload.lessons[:3])
        return (f"Book summary graphic for {payload.book_title} by {payload.book_author} "
                f"({payload.publication_year}), listing {payload.count} key lessons including {names}.")
    if isinstance(payload, ListPost):
        names = ", ".join(i.name for i in payload.items[:3])
        return f"Infographic titled '{payload.title}', listing {payload.count} points including {names}."
    if isinstance(payload, QuotePost):
        return f"Quote graphic: '{payload.quote_text}' {payload.attribution}."
    if isinstance(payload, MiniBlogPost):
        return f"Article headline graphic that reads: '{payload.headline}'."
    raise TypeError(f"Unknown payload type: {type(payload)!r}")
