"""Assemble the Facebook caption text for each post format.

The image carries the headline-level text; the caption carries the body. For
lists, the numbered items live here (the image shows only the title).
"""
from __future__ import annotations

from typing import Union

from schemas import ListPost, MiniBlogPost, QuotePost

PostPayload = Union[QuotePost, MiniBlogPost, ListPost]

# Gentle, on-brand hashtags. Deliberately avoids hype tags and the banned
# "financial freedom" framing.
HASHTAGS = "#personalfinance #moneymindset #financialcalm #frugalliving #moneyhabits"


def build(payload: PostPayload) -> str:
    if isinstance(payload, QuotePost):
        body = f"{payload.quote_text}\n\n{payload.caption_body}\n\n{payload.closing_question}"
    elif isinstance(payload, MiniBlogPost):
        body = f"{payload.caption_body}\n\n{payload.closing_question}"
    elif isinstance(payload, ListPost):
        lines = [payload.title, "", payload.intro_line, ""]
        for i, item in enumerate(payload.items, 1):
            lines.append(f"{i}. {item.name} — {item.explanation}")
        lines += ["", payload.closing_line]
        body = "\n".join(lines)
    else:
        raise TypeError(f"Unknown payload type: {type(payload)!r}")

    return f"{body}\n\n{HASHTAGS}"
