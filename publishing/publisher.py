"""Facebook Graph API publisher — posts a single photo with a caption.

Uploads the local PNG via multipart `source` (no external image host needed)
to /{page-id}/photos with `message` as the caption. Honors DRY_RUN (writes the
image + caption to data/generated_images/dry_run/ instead of calling the API)
and the KILL_SWITCH (refuses to publish). Retries transient failures with
exponential backoff.

Returns the Facebook post id on success.
"""
from __future__ import annotations

import time
from pathlib import Path

import requests

import config


class PublishError(RuntimeError):
    """Raised when publishing ultimately fails after retries."""


class KillSwitchActive(RuntimeError):
    """Raised when KILL_SWITCH is set — publishing is paused."""


def _base() -> str:
    return f"https://graph.facebook.com/{config.FB_GRAPH_VERSION}"


def _dry_run_publish(image_path: Path, caption: str) -> str:
    out_dir = config.GENERATED_IMAGES_DIR / "dry_run"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = image_path.stem
    (out_dir / f"{stem}.caption.txt").write_text(caption, encoding="utf-8")
    # copy the image alongside the caption for easy review
    dest = out_dir / image_path.name
    if image_path.resolve() != dest.resolve():
        dest.write_bytes(image_path.read_bytes())
    print(f"[DRY_RUN] would post {image_path.name} -> {out_dir}")
    return f"dryrun_{stem}"


def publish(image_path: Path, caption: str, *, max_retries: int = 3) -> str:
    """Publish a photo post. Returns the FB post id (or a dryrun_ id in DRY_RUN)."""
    if config.kill_switch_active():
        raise KillSwitchActive(
            "Publishing is paused (KILL_SWITCH env var or flag file "
            f"{config.KILL_SWITCH_FILE} present)."
        )

    if config.DRY_RUN:
        return _dry_run_publish(image_path, caption)

    config.require("FB_PAGE_ID", "FB_PAGE_ACCESS_TOKEN")
    url = f"{_base()}/{config.FB_PAGE_ID}/photos"

    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            with open(image_path, "rb") as fh:
                resp = requests.post(
                    url,
                    data={
                        "message": caption,
                        "access_token": config.FB_PAGE_ACCESS_TOKEN,
                        "published": "true",
                    },
                    files={"source": fh},
                    timeout=120,
                )
            if resp.ok:
                data = resp.json()
                # /photos returns {"id": photo_id, "post_id": page_post_id}
                return data.get("post_id") or data.get("id", "")
            # 4xx (bad token, policy) won't be fixed by retrying — fail fast.
            if 400 <= resp.status_code < 500:
                raise PublishError(f"Facebook API {resp.status_code}: {resp.text}")
            last_err = PublishError(f"Facebook API {resp.status_code}: {resp.text}")
        except (requests.RequestException, PublishError) as e:
            last_err = e
            if isinstance(e, PublishError) and "API 4" in str(e):
                raise
        if attempt < max_retries:
            backoff = 2 ** attempt
            print(f"publish attempt {attempt} failed ({last_err}); retrying in {backoff}s")
            time.sleep(backoff)

    raise PublishError(f"Publishing failed after {max_retries} attempts: {last_err}")
