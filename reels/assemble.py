"""Assemble the final 1080x1920 reel with ffmpeg.

Cuts every ~2 seconds (cycling the b-roll clips) because long static footage under
continuous VO is the fastest retention drop in this format. Footage is dimmed so
the burned-in text is the primary visual. Then it burns the hook + key-stat +
karaoke captions and mixes the voiceover with (ducked) music. Runs from a temp
dir so the subtitles filter can use a relative path.
"""
from __future__ import annotations

import logging
import math
import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg

import config
from reels.captions import build_ass
from reels.voice import Word

log = logging.getLogger("calm_money.reels.assemble")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
CUT_SECONDS = 2.2  # cut cadence
# fill vertical, then dim so text pops
VF = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,"
      "fps=30,drawbox=x=0:y=0:w=1080:h=1920:color=black@0.34:t=fill")


def _run(args: list[str], cwd: Path) -> None:
    proc = subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args],
                          cwd=str(cwd), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(args[:6])}...\n{proc.stderr[-800:]}")


def assemble(clips: list[Path], vo_path: Path, words: list[Word], out_path: Path, *,
             hook_text: str, hook_span: tuple[float, float],
             stat_text: str | None = None, stat_span: tuple[float, float] | None = None,
             music_path: Path | None = None) -> Path:
    duration = (words[-1].end + 0.6) if words else config.REEL_TARGET_SECONDS
    work = out_path.parent / "_work"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    font_src = config.FONTS_DIR / "Inter.ttf"
    if font_src.exists():
        shutil.copy(font_src, work / "Inter.ttf")

    build_ass(words, work / "captions.ass", hook_text=hook_text, hook_span=hook_span,
              stat_text=stat_text, stat_span=stat_span)

    # cut into ~CUT_SECONDS segments, cycling clips (frequent cuts)
    n_segs = max(1, math.ceil(duration / CUT_SECONDS))
    seg_files = []
    for j in range(n_segs):
        clip = clips[j % len(clips)]
        seg = f"seg{j}.mp4"
        _run(["-stream_loop", "-1", "-i", str(clip), "-t", f"{CUT_SECONDS:.3f}", "-an",
              "-vf", VF, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high", seg], work)
        seg_files.append(seg)

    (work / "concat.txt").write_text("".join(f"file '{s}'\n" for s in seg_files), encoding="utf-8")
    _run(["-f", "concat", "-safe", "0", "-i", "concat.txt", "-c", "copy", "broll.mp4"], work)

    args: list[str] = ["-i", "broll.mp4", "-i", str(vo_path)]
    if music_path:
        args += ["-stream_loop", "-1", "-i", str(music_path)]
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
