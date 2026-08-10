"""Assemble the final 1080x1920 reel with ffmpeg.

Normalizes each b-roll clip to a vertical segment, concatenates them to cover the
voiceover, then burns the karaoke captions and mixes the voiceover with (ducked)
music. All work happens in a temp dir so the subtitles filter can use a relative
path (Windows path escaping in filtergraphs is otherwise painful).
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg

import config
from reels.captions import build_ass
from reels.voice import Word

log = logging.getLogger("calm_money.reels.assemble")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
VF_FILL = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30"


def _run(args: list[str], cwd: Path) -> None:
    proc = subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args],
                          cwd=str(cwd), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(args[:6])}...\n{proc.stderr[-800:]}")


def assemble(clips: list[Path], vo_path: Path, words: list[Word], hook_text: str,
             out_path: Path, music_path: Path | None = None) -> Path:
    duration = (words[-1].end + 0.6) if words else config.REEL_TARGET_SECONDS
    work = out_path.parent / "_work"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    # font for the subtitle burn (fontsdir=.)
    font_src = config.FONTS_DIR / "Inter.ttf"
    if font_src.exists():
        shutil.copy(font_src, work / "Inter.ttf")

    # captions
    build_ass(words, hook_text, work / "captions.ass")

    # normalize each clip to an equal-length vertical segment
    seg_len = max(2.0, duration / max(1, len(clips)))
    seg_files = []
    for i, clip in enumerate(clips):
        seg = f"seg{i}.mp4"
        _run(["-stream_loop", "-1", "-i", str(clip), "-t", f"{seg_len:.3f}", "-an",
              "-vf", VF_FILL, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high", seg], work)
        seg_files.append(seg)

    # concat segments
    (work / "concat.txt").write_text("".join(f"file '{s}'\n" for s in seg_files), encoding="utf-8")
    _run(["-f", "concat", "-safe", "0", "-i", "concat.txt", "-c", "copy", "broll.mp4"], work)

    # final: burn captions + mix audio
    args: list[str] = ["-i", "broll.mp4", "-i", str(vo_path)]
    if music_path:
        args += ["-stream_loop", "-1", "-i", str(music_path)]
    # build filter_complex
    if music_path:
        filt = (
            "[0:v]subtitles=captions.ass:fontsdir=.[v];"
            f"[2:a]volume={config.REEL_MUSIC_VOLUME}[m];"
            "[1:a][m]amix=inputs=2:duration=first:dropout_transition=200[a]"
        )
        maps = ["-map", "[v]", "-map", "[a]"]
    else:
        filt = "[0:v]subtitles=captions.ass:fontsdir=.[v]"
        maps = ["-map", "[v]", "-map", "1:a"]

    _run([*args, "-filter_complex", filt, *maps, "-t", f"{duration:.3f}", "-r", "30",
          "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high",
          "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
          str(out_path.resolve())], work)

    shutil.rmtree(work, ignore_errors=True)
    return out_path
