"""Voiceover via Microsoft Edge neural TTS (edge-tts) — free, no API key.

Returns the mp3 path and per-word timings, which drive the karaoke captions.
edge-tts is an unofficial interface to Edge's read-aloud voices; if it ever
changes, this is the module to adjust.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import edge_tts

import config


@dataclass
class Word:
    text: str
    start: float  # seconds
    end: float


async def _synth(text: str, voice: str, out_path: str) -> list[Word]:
    words: list[Word] = []
    comm = edge_tts.Communicate(text, voice, boundary="WordBoundary")
    with open(out_path, "wb") as fh:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                fh.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                start = ch["offset"] / 1e7
                words.append(Word(ch["text"], start, start + ch["duration"] / 1e7))
    return words


def synthesize(text: str, out_path: Path, voice: str | None = None) -> list[Word]:
    """Synthesize `text` to an mp3 at out_path; return per-word timings."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return asyncio.run(_synth(text, voice or config.EDGE_TTS_VOICE, str(out_path)))
