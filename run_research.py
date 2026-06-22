"""Entry point: run the research layer to top up the topic queue.

    python run_research.py                # generate briefs and insert them
    python run_research.py -n 8           # request 8 briefs
    python run_research.py --dry          # print briefs, do NOT insert
    python run_research.py --verify       # also HTTP-check each source URL

Designed to be scheduled twice daily (2 PM and 10 PM Dhaka) via research.bat.
Requires GEMINI_API_KEY.
"""
from __future__ import annotations

import argparse
import logging

import requests

import config
import logging_setup
from db import init_db


def _verify_url(url: str) -> str:
    try:
        r = requests.head(url, timeout=15, allow_redirects=True)
        if r.status_code >= 400:
            r = requests.get(url, timeout=15, allow_redirects=True, stream=True)
        return f"{r.status_code}"
    except requests.RequestException as e:
        return f"ERR {type(e).__name__}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate research briefs.")
    ap.add_argument("-n", type=int, default=None, help="Number of briefs to request.")
    ap.add_argument("--dry", action="store_true", help="Print briefs without inserting.")
    ap.add_argument("--verify", action="store_true", help="HTTP-check each source URL.")
    args = ap.parse_args()

    logging_setup.setup()
    init_db()
    log = logging.getLogger("calm_money.research")

    config.require("GEMINI_API_KEY")
    from research import researcher

    try:
        briefs = researcher.generate_briefs(args.n)
    except Exception as e:
        log.error("research run failed: %s", e)  # ERROR -> Telegram alert
        return 1
    print(f"\nGenerated {len(briefs)} brief(s) "
          f"(grounding={'on' if config.RESEARCH_USE_GROUNDING else 'off'}):\n")
    for i, b in enumerate(briefs, 1):
        print(f"{i}. [{b.well_id}] {b.angle_title}")
        print(f"   format: {b.suggested_format}"
              + (f" ({b.suggested_list_count})" if b.suggested_list_count else "")
              + f" · evergreen: {b.evergreen}")
        print(f"   {b.angle_summary}")
        for f in b.supporting_facts:
            status = f"  [{_verify_url(f.source_url)}]" if args.verify else ""
            print(f"   - {f.source_name}: {f.source_url}{status}")
        print()

    if args.dry:
        print("--dry: nothing inserted.")
        return 0

    import store
    inserted = store.seed_briefs(briefs)
    print(f"Inserted {inserted} new brief(s). Available now:")
    for fmt in config.FORMAT_TYPES:
        print(f"  {fmt:<9}: {store.count_available(fmt)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
