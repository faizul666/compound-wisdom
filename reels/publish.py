"""Publish a reel to a Facebook Page via the Reels API (resumable upload).

Flow: start -> upload binary -> finish(PUBLISHED). Honors DRY_RUN (copies the
mp4 + caption locally) and the kill switch. Returns the FB video id.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

import config

log = logging.getLogger("calm_money.reels.publish")


class ReelPublishError(RuntimeError):
    pass


def _dry_run(video_path: Path, caption: str) -> str:
    out = config.REELS_DIR / "dry_run"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{video_path.stem}.caption.txt").write_text(caption, encoding="utf-8")
    dest = out / video_path.name
    if video_path.resolve() != dest.resolve():
        dest.write_bytes(video_path.read_bytes())
    log.info("[DRY_RUN] reel staged -> %s", dest)
    return f"dryrun_{video_path.stem}"


def publish(video_path: Path, caption: str) -> str:
    from publishing.publisher import KillSwitchActive
    if config.kill_switch_active():
        raise KillSwitchActive("Publishing paused (kill switch).")
    if config.DRY_RUN:
        return _dry_run(video_path, caption)

    config.require("FB_PAGE_ID", "FB_PAGE_ACCESS_TOKEN")
    token = config.FB_PAGE_ACCESS_TOKEN
    base = f"https://graph.facebook.com/{config.FB_GRAPH_VERSION}/{config.FB_PAGE_ID}/video_reels"

    # 1) start
    start = requests.post(base, data={"upload_phase": "start", "access_token": token}, timeout=60)
    if not start.ok:
        raise ReelPublishError(f"reel start failed: {start.status_code} {start.text}")
    sj = start.json()
    video_id, upload_url = sj["video_id"], sj["upload_url"]

    # 2) upload the binary
    size = video_path.stat().st_size
    with open(video_path, "rb") as fh:
        up = requests.post(
            upload_url,
            headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)},
            data=fh.read(),
            timeout=600,
        )
    if not up.ok:
        raise ReelPublishError(f"reel upload failed: {up.status_code} {up.text}")

    # 3) finish + publish
    fin = requests.post(base, data={
        "upload_phase": "finish", "video_id": video_id,
        "video_state": "PUBLISHED", "description": caption, "access_token": token,
    }, timeout=120)
    if not fin.ok:
        raise ReelPublishError(f"reel finish failed: {fin.status_code} {fin.text}")

    log.info("reel published; video_id=%s (may take a minute to process)", video_id)
    return video_id
