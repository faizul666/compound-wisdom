"""Pillow image composer — renders one branded title card per post.

Per the format design, the image carries only the headline-level text (the
quote, the mini-blog headline, or the list title); the body/list lives in the
caption. Rendering is fully deterministic: the same content always produces the
same PNG (no random elements), so a retry never yields a different image.

Each named template (from the schemas) maps to a Style: a background treatment,
a palette, and a font choice. Weights come from the variable fonts' Weight axis.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, Union

from PIL import Image, ImageDraw, ImageFont

import config
from schemas import ListPost, MiniBlogPost, QuotePost

PostPayload = Union[QuotePost, MiniBlogPost, ListPost]

# Canvas sizes
SQUARE = (1080, 1080)        # quotes
PORTRAIT = (1080, 1350)      # mini-blog + list
MARGIN = 110
BRAND = "CALM MONEY DAILY"

FontFamily = Literal["serif", "display", "sans"]
_FONT_FILES = {"serif": "Lora.ttf", "display": "Playfair.ttf", "sans": "Inter.ttf"}


# --------------------------------------------------------------------------
# Fonts
# --------------------------------------------------------------------------
@lru_cache(maxsize=256)
def font(family: FontFamily, size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    path = config.FONTS_DIR / _FONT_FILES[family]
    f = ImageFont.truetype(str(path), size)
    try:
        axes = f.get_variation_axes()
        values = []
        for ax in axes:
            name = ax.get("name", b"")
            name = name.decode("latin-1") if isinstance(name, bytes) else str(name)
            low = name.lower()
            if "weight" in low or "wght" in low:
                values.append(weight)
            elif "optical" in low or "opsz" in low:
                values.append(min(max(size, ax["minimum"]), ax["maximum"]))
            else:
                values.append(ax["default"])
        if values:
            f.set_variation_by_axes(values)
    except Exception:
        pass  # static font or no axes — use as-is
    return f


# --------------------------------------------------------------------------
# Palette + style
# --------------------------------------------------------------------------
Color = tuple[int, int, int]


@dataclass(frozen=True)
class Style:
    bg: Literal["gradient", "solid", "card", "dark"]
    top: Color                # gradient top / solid / card surround
    bottom: Color             # gradient bottom (== top for solid)
    ink: Color                # primary text
    accent: Color             # kicker / rule / attribution
    title_family: FontFamily
    title_weight: int = 600
    card: Color = (0, 0, 0)   # inner card fill (for bg == "card")


# Calm, warm, low-saturation palettes. No pure white, no harsh black.
_CREAM = (244, 238, 228)
_INK = (43, 42, 38)
_TAN = (176, 137, 104)
_GREEN = (47, 74, 63)
_DARK = (30, 42, 36)

QUOTE_TEMPLATES: dict[str, Style] = {
    "warm_gradient": Style("gradient", (246, 231, 216), (233, 207, 184), _INK, _TAN, "serif", 600),
    "parchment": Style("solid", (239, 231, 214), (239, 231, 214), (58, 53, 44), (150, 120, 86), "serif", 500),
    "minimal_photo": Style("solid", (243, 241, 236), (243, 241, 236), (52, 50, 46), (150, 120, 86), "sans", 500),
    "branded_solid": Style("dark", _GREEN, _GREEN, (242, 239, 230), (197, 168, 128), "display", 600),
    "serif_card": Style("card", (231, 222, 207), (231, 222, 207), (49, 45, 38), _TAN, "serif", 600, card=_CREAM),
}

MINIBLOG_TEMPLATES: dict[str, Style] = {
    "bold_sans": Style("solid", (243, 241, 236), (243, 241, 236), (38, 37, 34), _TAN, "sans", 700),
    "editorial_serif": Style("solid", _CREAM, _CREAM, (43, 42, 38), _TAN, "display", 600),
    "warm_serif": Style("gradient", (246, 231, 216), (232, 211, 192), _INK, _TAN, "serif", 600),
    "minimal_photo_overlay": Style("dark", _DARK, _DARK, (237, 234, 224), (197, 168, 128), "sans", 600),
}

LIST_TEMPLATES: dict[str, Style] = {
    "numbered_bold": Style("solid", (243, 241, 236), (243, 241, 236), (38, 37, 34), _TAN, "sans", 700),
    "serif_list_card": Style("card", (231, 222, 207), (231, 222, 207), (49, 45, 38), _TAN, "serif", 600, card=_CREAM),
    "warm_gradient_list": Style("gradient", (246, 231, 216), (233, 207, 184), _INK, _TAN, "display", 600),
    "minimal_dark": Style("dark", _DARK, _DARK, (237, 234, 224), (197, 168, 128), "sans", 600),
}


# --------------------------------------------------------------------------
# Drawing primitives
# --------------------------------------------------------------------------
def _lerp(a: Color, b: Color, t: float) -> Color:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore


def _background(size: tuple[int, int], style: Style) -> Image.Image:
    img = Image.new("RGB", size, style.top)
    if style.bg == "gradient":
        w, h = size
        px = img.load()
        for y in range(h):
            row = _lerp(style.top, style.bottom, y / max(h - 1, 1))
            for x in range(w):
                px[x, y] = row
    elif style.bg == "card":
        d = ImageDraw.Draw(img)
        inset = 56
        d.rounded_rectangle([inset, inset, size[0] - inset, size[1] - inset],
                            radius=28, fill=style.card)
    return img


def _wrap(text: str, fnt: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        cur = words[0]
        for word in words[1:]:
            if fnt.getlength(cur + " " + word) <= max_w:
                cur += " " + word
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def _fit(text: str, family: FontFamily, weight: int, max_w: int, max_h: int,
         hi: int, lo: int = 30, line_spacing: float = 1.18):
    """Largest font size in [lo, hi] whose wrapped text fits max_w x max_h."""
    best = lo
    best_lines: list[str] = [text]
    for size in range(hi, lo - 1, -2):
        fnt = font(family, size, weight)
        lines = _wrap(text, fnt, max_w)
        if any(fnt.getlength(ln) > max_w for ln in lines):
            continue
        line_h = size * line_spacing
        if line_h * len(lines) <= max_h:
            return fnt, lines, size
        best, best_lines = size, lines  # smallest tried so far; keep as fallback
    # nothing fit cleanly within max_h — return the smallest size's wrap anyway
    return font(family, best, weight), best_lines, best


def _draw_block(draw: ImageDraw.ImageDraw, lines: list[str], fnt: ImageFont.FreeTypeFont,
                cx: int, top: int, fill: Color, line_spacing: float = 1.18,
                align: str = "center") -> int:
    line_h = fnt.size * line_spacing
    y = top
    for ln in lines:
        w = fnt.getlength(ln)
        x = cx - w / 2 if align == "center" else cx
        draw.text((x, y), ln, font=fnt, fill=fill)
        y += line_h
    return round(y)


def _kicker(draw: ImageDraw.ImageDraw, text: str, cx: int, y: int, style: Style) -> None:
    """Small letter-spaced label with a short rule beneath it."""
    fnt = font("sans", 28, 600)
    spaced = " ".join(text.upper())
    w = fnt.getlength(spaced)
    draw.text((cx - w / 2, y), spaced, font=fnt, fill=style.accent)
    ry = y + 48
    draw.line([(cx - 34, ry), (cx + 34, ry)], fill=style.accent, width=3)


def _footer(draw: ImageDraw.ImageDraw, size: tuple[int, int], style: Style) -> None:
    fnt = font("sans", 24, 600)
    spaced = " ".join(BRAND)
    w = fnt.getlength(spaced)
    draw.text(((size[0] - w) / 2, size[1] - 92), spaced, font=fnt, fill=style.accent)


def _well_label(well_id: str) -> str:
    return well_id.replace("_", " ")


# --------------------------------------------------------------------------
# Per-format renderers
# --------------------------------------------------------------------------
def _render_quote(p: QuotePost, well_id: str) -> Image.Image:
    style = QUOTE_TEMPLATES[p.image_background_template]
    size = SQUARE
    img = _background(size, style)
    draw = ImageDraw.Draw(img)
    cx = size[0] // 2
    max_w = size[0] - 2 * MARGIN

    # large decorative quote mark
    qm = font("display", 150, 700)
    draw.text((MARGIN - 6, 110), "“", font=qm, fill=style.accent)

    fnt, lines, _ = _fit(p.quote_text, style.title_family, style.title_weight,
                         max_w, 620, hi=92, lo=46)
    block_h = fnt.size * 1.2 * len(lines)
    top = (size[1] - block_h) / 2 - 10
    end = _draw_block(draw, lines, fnt, cx, int(top), style.ink, 1.2)

    # attribution
    afnt = font("sans", 30, 500)
    aw = afnt.getlength(p.attribution)
    draw.text((cx - aw / 2, end + 26), p.attribution, font=afnt, fill=style.accent)

    _footer(draw, size, style)
    return img


def _render_miniblog(p: MiniBlogPost, well_id: str) -> Image.Image:
    style = MINIBLOG_TEMPLATES[p.headline_image_template]
    size = PORTRAIT
    img = _background(size, style)
    draw = ImageDraw.Draw(img)
    cx = size[0] // 2
    max_w = size[0] - 2 * MARGIN

    _kicker(draw, _well_label(well_id), cx, 150, style)

    fnt, lines, _ = _fit(p.headline, style.title_family, style.title_weight,
                         max_w, 720, hi=104, lo=48)
    block_h = fnt.size * 1.16 * len(lines)
    top = (size[1] - block_h) / 2 - 20
    _draw_block(draw, lines, fnt, cx, int(top), style.ink, 1.16)

    _footer(draw, size, style)
    return img


def _render_list(p: ListPost, well_id: str) -> Image.Image:
    style = LIST_TEMPLATES[p.list_image_template]
    size = PORTRAIT
    img = _background(size, style)
    draw = ImageDraw.Draw(img)
    cx = size[0] // 2
    max_w = size[0] - 2 * MARGIN

    # count badge
    badge_fnt = font("sans", 120, 700)
    num = str(p.count)
    nw = badge_fnt.getlength(num)
    draw.text((cx - nw / 2, 196), num, font=badge_fnt, fill=style.accent)
    klabel = font("sans", 26, 600)
    spaced = " ".join("THINGS TO KNOW")
    kw = klabel.getlength(spaced)
    draw.text((cx - kw / 2, 340), spaced, font=klabel, fill=style.ink)

    fnt, lines, _ = _fit(p.title, style.title_family, style.title_weight,
                         max_w, 560, hi=84, lo=44)
    block_h = fnt.size * 1.18 * len(lines)
    top = 470 + (560 - block_h) / 2
    _draw_block(draw, lines, fnt, cx, int(top), style.ink, 1.18)

    _footer(draw, size, style)
    return img


_RENDERERS = {
    QuotePost: _render_quote,
    MiniBlogPost: _render_miniblog,
    ListPost: _render_list,
}


def _slug(payload: PostPayload) -> str:
    raw = payload.model_dump_json()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def render(payload: PostPayload, well_id: str, out_dir: Path | None = None) -> Path:
    """Render `payload` to a PNG and return its path. Deterministic filename."""
    renderer = _RENDERERS.get(type(payload))
    if renderer is None:
        raise TypeError(f"No renderer for {type(payload)!r}")
    out_dir = out_dir or config.GENERATED_IMAGES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    fmt = {QuotePost: "quote", MiniBlogPost: "miniblog", ListPost: "list"}[type(payload)]
    path = out_dir / f"{fmt}_{_slug(payload)}.png"
    img = renderer(payload, well_id)
    img.save(path, "PNG")
    return path
