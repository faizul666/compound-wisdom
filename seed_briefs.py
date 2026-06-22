"""Seed the research_briefs table from the mock briefs.

Until the live research layer (Phase 3) is built, this populates the topic
queue so the scheduler has briefs to draw from. Idempotent — re-running only
inserts briefs whose angle_title isn't already present.

    python seed_briefs.py
"""
from db import init_db
from store import count_available, seed_briefs
from tests.mock_briefs import all_briefs


def main() -> None:
    init_db()
    inserted = seed_briefs(all_briefs())
    print(f"Seeded {inserted} new briefs.")
    for fmt in ("quote", "mini_blog", "list"):
        print(f"  available {fmt:<9}: {count_available(fmt)}")
    print(f"  available total  : {count_available()}")


if __name__ == "__main__":
    main()
