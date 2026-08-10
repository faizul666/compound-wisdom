"""Assemble the Facebook caption text for each post format.

The image carries the headline-level text (and, for book summaries, the cover);
the caption carries the body — the numbered lessons/items live here.
"""
from __future__ import annotations

from typing import Union

from schemas import BookSummaryPost, ListPost, MiniBlogPost, QuotePost

PostPayload = Union[QuotePost, MiniBlogPost, ListPost, BookSummaryPost]

# Broad self-improvement hashtags (advertiser-friendly, no hype tags).
HASHTAGS = "#books #booksummary #selfimprovement #mindset #personalgrowth #wisdom"


def build(payload: PostPayload) -> str:
    if isinstance(payload, QuotePost):
        body = f"“{payload.quote_text}”\n{payload.attribution}\n\n{payload.caption_body}\n\n{payload.closing_question}"
    elif isinstance(payload, MiniBlogPost):
        body = f"{payload.caption_body}\n\n{payload.closing_question}"
    elif isinstance(payload, ListPost):
        lines = [payload.title, "", payload.intro_line, ""]
        for i, item in enumerate(payload.items, 1):
            lines.append(f"{i}. {item.name} — {item.explanation}")
        lines += ["", payload.closing_line]
        body = "\n".join(lines)
    elif isinstance(payload, BookSummaryPost):
        lines = [f"{payload.headline}", f"by {payload.book_author}", "", payload.intro_line, ""]
        for i, lesson in enumerate(payload.lessons, 1):
            lines.append(f"{i}. {lesson.lesson} — {lesson.detail}")
        lines += ["", payload.closing_line,
                  "", f"\U0001F4D6 Book: {payload.book_title} by {payload.book_author}"]
        body = "\n".join(lines)
    else:
        raise TypeError(f"Unknown payload type: {type(payload)!r}")

    return f"{body}\n\n{HASHTAGS}"
