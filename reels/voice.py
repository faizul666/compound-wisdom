"""Voiceover via Microsoft Edge neural TTS (edge-tts) — free, no API key.

synthesize_beats() speaks each of the 5 script beats separately, trims each to
its speech length, and concatenates them with a short silence between beats
(a deliberate pause before each payoff — the biggest tell of flat AI VO is the
absence of pauses). Runs slightly fast (energetic on Reels). Returns combined
per-word timings plus each beat's (start, end) span, which drive the captions.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import edge_tts
import imageio_ffmpeg

import config

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


@dataclass
class Word:
    text: str
    start: float
    end: float


async def _synth_one(text: str, voice: str, rate: str, out_path: str) -> list[Word]:
    words: list[Word] = []
    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    with open(out_path, "wb") as fh:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                fh.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                start = ch["offset"] / 1e7
                words.append(Word(ch["text"], start, start + ch["duration"] / 1e7))
    return words


def _ff(args: list[str]) -> None:
    p = subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg (voice) failed: {p.stderr[-400:]}")


def synthesize(text: str, out_path: Path, voice: str | None = None, rate: str = "+8%") -> list[Word]:
    """Single-segment synthesis (used for quick tests)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return asyncio.run(_synth_one(text, voice or config.EDGE_TTS_VOICE, rate, str(out_path)))


def synthesize_beats(beats: list[str], out_path: Path, voice: str | None = None,
                     rate: str = "+8%", pause: float = 0.4
                     ) -> tuple[list[Word], list[tuple[float, float]]]:
    """Synthesize beats with `pause` seconds of silence between them.

    Returns (combined_words, beat_spans) with all timings on the final timeline.
    """
    voice = voice or config.EDGE_TTS_VOICE
    out_path.parent.mkdir(parents=True, exist_ok=True)
    work = out_path.parent / "_vo"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    # silence segment (match edge-tts output: 24kHz mono mp3)
    sil = work / "sil.mp3"
    _ff(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{pause:.3f}",
         "-c:a", "libmp3lame", "-b:a", "48k", str(sil)])

    combined: list[Word] = []
    spans: list[tuple[float, float]] = []
    concat_files: list[str] = []
    offset = 0.0
    for i, beat in enumerate(beats):
        raw = work / f"beat{i}.mp3"
        words = asyncio.run(_synth_one(beat, voice, rate, str(raw)))
        beat_dur = (words[-1].end + 0.12) if words else 1.0
        trimmed = work / f"beat{i}_t.mp3"
        _ff(["-i", str(raw), "-t", f"{beat_dur:.3f}", "-c:a", "libmp3lame", "-b:a", "48k", str(trimmed)])

        for w in words:
            combined.append(Word(w.text, w.start + offset, w.end + offset))
        spans.append((offset, offset + beat_dur))
        concat_files.append(trimmed.name)
        offset += beat_dur
        if i < len(beats) - 1:
            concat_files.append(sil.name)
            offset += pause

    (work / "list.txt").write_text("".join(f"file '{f}'\n" for f in concat_files), encoding="utf-8")
    _ff(["-f", "concat", "-safe", "0", "-i", str(work / "list.txt"),
         "-c:a", "libmp3lame", "-b:a", "96k", str(out_path)])

    shutil.rmtree(work, ignore_errors=True)
    return combined, spans
