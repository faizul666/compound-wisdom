"""Build an ASS subtitle file: a bold hook title plus word-synced captions.

Captions are shown in short chunks (~3 words) timed from the voiceover's word
boundaries, big and centered-low the way high-retention reels do it. The file is
burned into the video by ffmpeg's subtitles filter.
"""
from __future__ import annotations

from pathlib import Path

from reels.voice import Word

# ASS colours are &HAABBGGRR (AA=alpha, 00 opaque).
WHITE = "&H00FFFFFF"
BLACK = "&H00000000"
ACCENT = "&H006889B0"  # warm tan (#B08968) in BGR

_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption, Inter, 82, {white}, {white}, {black}, {black}, -1, 0, 0, 0, 100, 100, 0, 0, 1, 7, 3, 2, 80, 80, 430, 1
Style: Hook, Inter, 104, {accent}, {accent}, {black}, {black}, -1, 0, 0, 0, 100, 100, 0, 0, 1, 8, 4, 8, 80, 80, 300, 1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".format(white=WHITE, black=BLACK, accent=ACCENT)


def _t(seconds: float) -> str:
    cs = max(0, int(round(seconds * 100)))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _chunk(words: list[Word], max_words: int = 3, max_chars: int = 22) -> list[list[Word]]:
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


def build_ass(words: list[Word], hook_text: str, out_path: Path) -> Path:
    lines = [_HEADER]

    # Hook title over the first few seconds.
    hook_end = 3.0
    if words:
        hook_end = min(3.2, max(2.0, words[min(5, len(words) - 1)].end))
    hook = hook_text.strip().upper().replace("\n", " ")
    lines.append(f"Dialogue: 0,{_t(0)},{_t(hook_end)},Hook,,0,0,0,,{hook}")

    # Word-synced caption chunks.
    for chunk in _chunk(words):
        start = chunk[0].start
        end = chunk[-1].end + 0.08
        text = " ".join(w.text for w in chunk).upper()
        lines.append(f"Dialogue: 0,{_t(start)},{_t(end)},Caption,,0,0,0,,{text}")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
