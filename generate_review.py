"""Phase 2 voice-test harness.

Generates 30 posts (10 quote, 10 mini-blog, 10 list) from the mock briefs in
tests/mock_briefs.py, runs each through the compliance gate, and writes a human
review file (Markdown) plus a machine-readable JSON dump into review/.

This publishes NOTHING. It exists so we can iterate on voice/prompts until the
output reads consistently on-brand before building anything downstream.

Usage:
    python generate_review.py            # all 30
    python generate_review.py --limit 3  # 3 per format (quick smoke test)

Requires GEMINI_API_KEY in .env.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import config
from generation import compliance, generator
from schemas import ListPost, MiniBlogPost, QuotePost
from tests.mock_briefs import all_briefs

REVIEW_DIR = config.BASE_DIR / "review"


def _format_payload_md(payload) -> str:
    """Render a generated post as readable Markdown."""
    if isinstance(payload, QuotePost):
        return "\n".join([
            f"> **{payload.quote_text}**",
            f">",
            f"> {payload.attribution}",
            "",
            f"*template: `{payload.image_background_template}`*",
            "",
            "**Caption**",
            "",
            payload.caption_body,
            "",
            f"**Closing question:** {payload.closing_question}",
        ])
    if isinstance(payload, MiniBlogPost):
        return "\n".join([
            f"### {payload.headline}",
            "",
            f"*template: `{payload.headline_image_template}`*",
            "",
            "**Caption**",
            "",
            payload.caption_body,
            "",
            f"**Closing question:** {payload.closing_question}",
        ])
    if isinstance(payload, ListPost):
        lines = [
            f"### {payload.title}",
            "",
            f"*template: `{payload.list_image_template}` · count: {payload.count}*",
            "",
            f"_{payload.intro_line}_",
            "",
        ]
        for i, item in enumerate(payload.items, 1):
            lines.append(f"{i}. **{item.name}** — {item.explanation}")
        lines += ["", f"_{payload.closing_line}_"]
        return "\n".join(lines)
    return repr(payload)


def run(limit: int | None) -> int:
    config.require("GEMINI_API_KEY")
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)

    briefs = all_briefs()
    if limit is not None:
        # take `limit` of each format, preserving order
        kept: list = []
        seen: dict[str, int] = {}
        for b in briefs:
            n = seen.get(b.suggested_format, 0)
            if n < limit:
                kept.append(b)
                seen[b.suggested_format] = n + 1
        briefs = kept

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    md_path = REVIEW_DIR / f"phase2_review_{ts}.md"
    json_path = REVIEW_DIR / f"phase2_posts_{ts}.json"

    md_blocks: list[str] = []
    json_records: list[dict] = []
    passed = failed = errored = 0

    print(f"Generating {len(briefs)} posts...\n")
    for idx, brief in enumerate(briefs, 1):
        label = f"[{idx:>2}/{len(briefs)}] {brief.suggested_format:<9} · {brief.well_id}"
        try:
            fmt, payload = generator.generate(brief)
            verdict = compliance.check(payload)
            status = "PASS" if verdict.pass_ else "FAIL"
            if verdict.pass_:
                passed += 1
            else:
                failed += 1
            print(f"{label} -> {status}  {('(' + ','.join(verdict.failed_checks) + ')') if verdict.failed_checks else ''}")

            md_blocks.append("\n".join([
                f"## {idx}. {brief.suggested_format.upper()} — {brief.well_id}",
                "",
                f"**Brief angle:** {brief.angle_title}",
                "",
                f"**Compliance:** {'✅ PASS' if verdict.pass_ else '❌ FAIL'}"
                + (f" — failed checks: {', '.join(verdict.failed_checks)}" if verdict.failed_checks else "")
                + f"  \n_{verdict.notes}_",
                "",
                _format_payload_md(payload),
                "",
                "---",
                "",
            ]))
            json_records.append({
                "index": idx,
                "format": fmt,
                "well_id": brief.well_id,
                "angle_title": brief.angle_title,
                "payload": payload.model_dump(),
                "compliance": verdict.model_dump(by_alias=True),
            })
        except Exception as e:
            errored += 1
            print(f"{label} -> ERROR  {e}")
            md_blocks.append("\n".join([
                f"## {idx}. {brief.suggested_format.upper()} — {brief.well_id}",
                "",
                f"**Brief angle:** {brief.angle_title}",
                "",
                f"**GENERATION ERROR:** {e}",
                "",
                "---",
                "",
            ]))
            json_records.append({
                "index": idx,
                "format": brief.suggested_format,
                "well_id": brief.well_id,
                "angle_title": brief.angle_title,
                "error": str(e),
            })
        time.sleep(0.5)  # gentle pacing for free-tier rate limits

    total = len(briefs)
    header = "\n".join([
        f"# Calm Money Daily — Phase 2 voice review",
        "",
        f"Generated {ts} UTC · model(quote/list)=`{config.MODEL_FLASH}` · "
        f"model(mini_blog)=`{config.miniblog_model()}` · judge=`{config.MODEL_LITE}`",
        "",
        f"**Results: {passed}/{total} passed compliance** · {failed} failed · {errored} errored",
        "",
        "> Target before proceeding to Phase 3: ≥28/30 pass *and* read on-brand.",
        "",
        "---",
        "",
    ])
    md_path.write_text(header + "\n".join(md_blocks), encoding="utf-8")
    json_path.write_text(json.dumps(json_records, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'='*54}")
    print(f"  {passed}/{total} passed · {failed} failed · {errored} errored")
    print(f"  Review : {md_path}")
    print(f"  JSON   : {json_path}")
    print(f"{'='*54}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate 30 posts and review compliance.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Posts per format (default: all 10). Use a small number for a smoke test.")
    args = ap.parse_args()
    return run(args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
