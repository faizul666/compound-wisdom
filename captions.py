"""Facebook caption + alt-text for each static post format.

Since July 2025 Facebook captions and custom alt text are indexed by Google, so
these are written search-first: line 1 is a searchable claim + entity (before the
~125-char "See more" cut), the body carries the value, and a metadata line +
per-post hashtags give crawlers and AI answer engines clean entity signals.

The image carries only headline-level text; the numbered items/lessons live here.
alt_text() returns the entity-rich sentence for the photo's alt_text_custom.
"""
from __future__ import annotations

from typing import Union

from schemas import BookSummaryPost, ListPost, MiniBlogPost, QuotePost

PostPayload = Union[QuotePost, MiniBlogPost, ListPost, BookSummaryPost]


def _tags(hashtags: list[str]) -> str:
    seen, out = set(), []
    for h in hashtags:
        t = "#" + h.strip().lstrip("#").replace(" ", "")
        if t.lower() not in seen and len(t) > 1:
            seen.add(t.lower())
            out.append(t)
    return " ".join(out)


def build(payload: PostPayload) -> str:
    if isinstance(payload, BookSummaryPost):
        lines = [payload.caption_hook, "", payload.intro_line, ""]
        for i, lesson in enumerate(payload.lessons, 1):
            lines.append(f"{i}. {lesson.lesson} — {lesson.detail}")
        lines += ["", payload.closing_line, "",
                  f"\U0001F4D6 {payload.book_title} by {payload.book_author} ({payload.publication_year})"]
        body = "\n".join(lines)
    elif isinstance(payload, ListPost):
        lines = [payload.caption_hook, "", payload.intro_line, ""]
        for i, item in enumerate(payload.items, 1):
            lines.append(f"{i}. {item.name} — {item.explanation}")
        lines += ["", payload.closing_line]
        body = "\n".join(lines)
    elif isinstance(payload, QuotePost):
        body = f"“{payload.quote_text}”\n{payload.attribution}\n\n{payload.caption_body}\n\n{payload.closing_question}"
    elif isinstance(payload, MiniBlogPost):
        body = f"{payload.caption_hook}\n\n{payload.caption_body}\n\n{payload.closing_question}"
    else:
        raise TypeError(f"Unknown payload type: {type(payload)!r}")

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
