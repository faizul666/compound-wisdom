"""Reel voiceover — Gemini native TTS (primary) with Microsoft Edge TTS fallback.

Gemini TTS (paid account) produces the voice; if it fails for any reason the code
falls back to Edge TTS (free, no key). Beats are concatenated with a short silence
between them (a deliberate pause before each payoff).

Neither Gemini TTS nor Edge gives word timestamps we can rely on uniformly, so
word timings are approximated per beat: measure the beat's audio duration and
distribute it across words by length (Edge's real boundaries are also available
but the approximation keeps both providers consistent). Returns (combined_words,
beat_spans) on the final timeline.
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

import config

log = logging.getLogger("calm_money.reels.voice")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
_MARKDOWN = re.compile(r"[*_`~#>|]+")


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
    p = subprocess.run([FFMPEG, "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", p.stderr)
    if not m:
        return 0.0
    h, mn, s = m.groups()
    return int(h) * 3600 + int(mn) * 60 + float(s)


def _clean_for_tts(text: str) -> str:
    """Strip markup so TTS never reads symbols aloud (e.g. *take* -> take)."""
    t = _MARKDOWN.sub("", text)
    t = t.replace("—", ", ").replace("–", ", ")
    return re.sub(r"\s+", " ", t).strip()


def _approx_words(text: str, duration: float) -> list[Word]:
    tokens = text.split()
    total = sum(len(t) for t in tokens) or 1
    out, t = [], 0.0
    for tok in tokens:
        d = duration * (len(tok) / total)
        out.append(Word(tok, t, t + d))
        t += d
    return out


# --------------------------------------------------------------------------
# Providers: each writes an audio file and returns (words, duration, path)
# --------------------------------------------------------------------------
async def _edge_stream(text: str, voice: str, rate: str, out_path: str) -> list[Word]:
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


def _edge_one(text: str, work: Path, i: int, voice: str, rate: str):
    path = work / f"beat{i}.mp3"
    words = asyncio.run(_edge_stream(text, voice, rate, str(path)))
    dur = (words[-1].end + 0.12) if words else 1.0
    return words, dur, path


def _gemini_one(text: str, work: Path, i: int):
    from google.genai import types

    from generation.generator import _client
    resp = _client().models.generate_content(
        model=config.GEMINI_TTS_MODEL,
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=config.GEMINI_TTS_VOICE)
                )
            ),
        ),
    )
    data = resp.candidates[0].content.parts[0].inline_data.data
    if not data or len(data) < 500:
        raise RuntimeError("Gemini TTS returned no audio")
    path = work / f"beat{i}.wav"
    path.write_bytes(data)
    dur = _audio_duration(path)
    if dur <= 0:
        raise RuntimeError("could not measure Gemini audio duration")
    return _approx_words(text, dur), dur, path


# --------------------------------------------------------------------------
def _assemble(synth_one, beats: list[str], out_path: Path, pause: float
              ) -> tuple[list[Word], list[tuple[float, float]]]:
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
        words, dur, apath = synth_one(beat, work, i)
        conv = work / f"beat{i}_c.mp3"
        _ff(["-i", str(apath), "-t", f"{dur:.3f}", "-ar", "24000", "-ac", "1",
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
    """Synthesize beats with pauses. Gemini TTS if a key is set, else/failover Edge."""
    evoice = voice or config.EDGE_TTS_VOICE
    out_path.parent.mkdir(parents=True, exist_ok=True)
    beats = [_clean_for_tts(b) for b in beats]

    if config.GEMINI_API_KEY:
        try:
            return _assemble(_gemini_one, beats, out_path, pause)
        except Exception as e:
            log.warning("Gemini TTS failed (%s); falling back to Edge TTS", e)
    return _assemble(lambda t, w, i: _edge_one(t, w, i, evoice, rate), beats, out_path, pause)


def synthesize(text: str, out_path: Path, voice: str | None = None, rate: str = "+8%") -> list[Word]:
    """Single-segment Edge synthesis (used for quick tests)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return asyncio.run(_edge_stream(text, voice or config.EDGE_TTS_VOICE, rate, str(out_path)))
