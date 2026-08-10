"""Fetch vertical b-roll clips from Pexels (free API key).

Downloads a handful of portrait clips matched to the script's keywords, enough
to cover the voiceover length. Returns local mp4 paths (order = play order).
"""
from __future__ import annotations

import logging
from pathlib import Path

import requests

import config

log = logging.getLogger("calm_money.reels.broll")
PEXELS_VIDEO = "https://api.pexels.com/videos/search"


def _best_portrait_file(video: dict) -> dict | None:
    files = [f for f in video.get("video_files", []) if f.get("height") and f.get("width")]
    if not files:
        return None
    portrait = [f for f in files if f["height"] >= f["width"]] or files
    # prefer ~1080-1920 tall, not absurdly large
    for f in sorted(portrait, key=lambda f: -(f["height"] or 0)):
        if 900 <= (f["height"] or 0) <= 2200:
            return f
    return portrait[0]


def fetch_clips(keywords: list[str], out_dir: Path, need_seconds: float,
                min_clips: int = 4, max_clips: int = 8) -> list[Path]:
    """Download portrait clips covering ~need_seconds. Returns their paths."""
    config.require("PEXELS_API_KEY")
    out_dir.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": config.PEXELS_API_KEY}

    paths: list[Path] = []
    seen: set[int] = set()
    total = 0.0
    for kw in keywords:
        if total >= need_seconds and len(paths) >= min_clips:
            break
        try:
            data = requests.get(
                PEXELS_VIDEO, headers=headers,
                params={"query": kw, "orientation": "portrait", "per_page": 4, "size": "medium"},
                timeout=30,
            ).json()
        except Exception as e:
            log.warning("pexels search failed for %r: %s", kw, e)
            continue
        for video in data.get("videos", []):
            if len(paths) >= max_clips:
                break
            if video["id"] in seen:
                continue
            seen.add(video["id"])
            pick = _best_portrait_file(video)
            if not pick:
                continue
            try:
                content = requests.get(pick["link"], timeout=90).content
                path = out_dir / f"broll_{video['id']}.mp4"
                path.write_bytes(content)
                paths.append(path)
                total += min(video.get("duration", 6) or 6, 8)
            except Exception as e:
                log.warning("clip download failed (%s): %s", video["id"], e)
    if not paths:
        raise RuntimeError("No b-roll clips could be fetched from Pexels.")
    return paths
