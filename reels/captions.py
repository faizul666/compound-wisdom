"""Build an ASS subtitle file for a reel: a hook title, a big key-stat card, and
word-synced captions (4-5 words per frame, high contrast for sound-off viewing).
Burned into the video by ffmpeg's subtitles filter.
"""
from __future__ import annotations

from pathlib import Path

from reels.voice import Word

# ASS colours are &HAABBGGRR (AA=alpha, 00 opaque).
WHITE = "&H00FFFFFF"
BLACK = "&H00000000"
ACCENT = "&H0066B6E8"  # warm gold-ish for pop on dimmed footage

_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption, Inter, 86, {white}, {white}, {black}, {black}, -1, 0, 0, 0, 100, 100, 0, 0, 1, 8, 3, 2, 70, 70, 440, 1
Style: Hook, Inter, 100, {accent}, {accent}, {black}, {black}, -1, 0, 0, 0, 100, 100, 0, 0, 1, 5, 8, 8, 70, 70, 300, 1
Style: Stat, Inter, 200, {accent}, {accent}, {black}, {black}, -1, 0, 0, 0, 100, 100, 0, 0, 1, 8, 6, 5, 60, 60, 0, 1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".format(white=WHITE, black=BLACK, accent=ACCENT)


def _t(seconds: float) -> str:
    cs = max(0, int(round(seconds * 100)))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _chunk(words: list[Word], max_words: int = 4, max_chars: int = 26) -> list[list[Word]]:
    chunks: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        cur.append(w)
        text = " ".join(x.text for x in cur)
        if len(cur) >= max_words or len(text) >= max_chars:
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)
    return chunks


def build_ass(words: list[Word], out_path: Path, hook_text: str | None = None,
              hook_span: tuple[float, float] | None = None,
              stat_text: str | None = None,
              stat_span: tuple[float, float] | None = None) -> Path:
    lines = [_HEADER]

    if hook_text and hook_span:
        text = hook_text.strip().upper().replace("\n", " ")
        lines.append(f"Dialogue: 0,{_t(hook_span[0])},{_t(hook_span[1])},Hook,,0,0,0,,{text}")

    if stat_text and stat_span:
        st = stat_text.strip().upper().replace("\n", " ")
        lines.append(f"Dialogue: 0,{_t(stat_span[0])},{_t(stat_span[1])},Stat,,0,0,0,,{st}")

    # Word-synced caption chunks; skip chunks fully inside the hook window so the
    # hook title stands alone for the first beat.
    hook_end = hook_span[1] if hook_span else 0.0
    for chunk in _chunk(words):
        start = chunk[0].start
        if start < hook_end - 0.05:
            continue
        end = chunk[-1].end + 0.06
        text = " ".join(w.text for w in chunk).upper()
        lines.append(f"Dialogue: 0,{_t(start)},{_t(end)},Caption,,0,0,0,,{text}")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
