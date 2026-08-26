"""Reel voiceover — Fish Audio (premium) with Microsoft Edge TTS as fallback.

If FISH_API_KEY is set, each beat is synthesized via Fish Audio; if that fails
for any reason, it falls back to Edge TTS (free, no key). Beats are concatenated
with a short silence between them (a deliberate pause before each payoff).

Fish Audio returns no timestamps, so word timings are approximated by measuring
each beat's audio duration and distributing it across the words by length — good
enough for the chunk-level karaoke captions. Edge TTS gives real per-word timings.
Returns (combined_words, beat_spans) on the final timeline.
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import edge_tts
import imageio_ffmpeg
import requests

import config

log = logging.getLogger("calm_money.reels.voice")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


@dataclass
class Word:
    text: str
    start: float
    end: float


def _ff(args: list[str]) -> None:
    p = subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg (voice) failed: {p.stderr[-400:]}")


def _audio_duration(path: Path) -> float:
    """Duration in seconds, parsed from ffmpeg's probe output."""
    p = subprocess.run([FFMPEG, "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", p.stderr)
    if not m:
        return 0.0
    h, mn, s = m.groups()
    return int(h) * 3600 + int(mn) * 60 + float(s)


def _approx_words(text: str, duration: float) -> list[Word]:
    """Distribute `duration` across the words of `text`, weighted by word length."""
    tokens = text.split()
    total = sum(len(t) for t in tokens) or 1
    out, t = [], 0.0
    for tok in tokens:
        d = duration * (len(tok) / total)
        out.append(Word(tok, t, t + d))
        t += d
    return out


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------
async def _edge_one(text: str, voice: str, rate: str, out_path: str) -> list[Word]:
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


def _fish_one(text: str, out_path: Path) -> None:
    headers = {"Authorization": f"Bearer {config.FISH_API_KEY}", "model": config.FISH_MODEL}
    body = {"text": text, "format": "mp3", "mp3_bitrate": 128}
    if config.FISH_VOICE_ID:
        body["reference_id"] = config.FISH_VOICE_ID
    r = requests.post("https://api.fish.audio/v1/tts", headers=headers, json=body, timeout=120)
    if not r.ok:
        raise RuntimeError(f"Fish Audio TTS {r.status_code}: {r.text[:200]}")
    out_path.write_bytes(r.content)
    if out_path.stat().st_size < 500:
        raise RuntimeError("Fish Audio returned no audio")


# --------------------------------------------------------------------------
# Beat assembly (shared)
# --------------------------------------------------------------------------
def _assemble(synth_one, beats, out_path: Path, pause: float
              ) -> tuple[list[Word], list[tuple[float, float]]]:
    """synth_one(text, raw_path) -> (words_relative, duration). Concats beats
    to out_path with `pause` silence between them; returns combined timings."""
    work = out_path.parent / "_vo"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    sil = work / "sil.mp3"
    _ff(["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{pause:.3f}",
         "-c:a", "libmp3lame", "-b:a", "48k", str(sil)])

    combined: list[Word] = []
    spans: list[tuple[float, float]] = []
    concat: list[str] = []
    offset = 0.0
    for i, beat in enumerate(beats):
        raw = work / f"beat{i}.mp3"
        words, dur = synth_one(beat, raw)
        conv = work / f"beat{i}_c.mp3"
        _ff(["-i", str(raw), "-t", f"{dur:.3f}", "-ar", "24000", "-ac", "1",
             "-c:a", "libmp3lame", "-b:a", "96k", str(conv)])
        for w in words:
            combined.append(Word(w.text, w.start + offset, w.end + offset))
        spans.append((offset, offset + dur))
        concat.append(conv.name)
        offset += dur
        if i < len(beats) - 1:
            concat.append(sil.name)
            offset += pause

    (work / "list.txt").write_text("".join(f"file '{f}'\n" for f in concat), encoding="utf-8")
    _ff(["-f", "concat", "-safe", "0", "-i", str(work / "list.txt"),
         "-c:a", "libmp3lame", "-b:a", "96k", str(out_path)])
    shutil.rmtree(work, ignore_errors=True)
    return combined, spans


def synthesize_beats(beats: list[str], out_path: Path, voice: str | None = None,
                     rate: str = "+8%", pause: float = 0.4
                     ) -> tuple[list[Word], list[tuple[float, float]]]:
    """Synthesize beats with pauses. Fish Audio if configured, else/failover Edge."""
    voice = voice or config.EDGE_TTS_VOICE
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def edge_one(text, raw):
        words = asyncio.run(_edge_one(text, voice, rate, str(raw)))
        dur = (words[-1].end + 0.12) if words else 1.0
        return words, dur

    def fish_one(text, raw):
        _fish_one(text, raw)
        dur = _audio_duration(raw)
        if dur <= 0:
            raise RuntimeError("could not measure Fish audio duration")
        return _approx_words(text, dur), dur

    if config.FISH_API_KEY:
        try:
            return _assemble(fish_one, beats, out_path, pause)
        except Exception as e:
            log.warning("Fish Audio failed (%s); falling back to Edge TTS", e)
    return _assemble(edge_one, beats, out_path, pause)


def synthesize(text: str, out_path: Path, voice: str | None = None, rate: str = "+8%") -> list[Word]:
    """Single-segment Edge synthesis (used for quick tests)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return asyncio.run(_edge_one(text, voice or config.EDGE_TTS_VOICE, rate, str(out_path)))
