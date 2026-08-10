# Compound Wisdom

An autonomous content engine for a broad self-improvement Facebook page. It
distills the best ideas from bestselling non-fiction into four post formats —
**book summary** (with the real book cover), **list**, **author quote**, and
**mini-blog** — runs them through a compliance & quality gate, renders branded
images with Pillow, and schedules/publishes to Facebook. Zero manual input once
running.

Three pillars: **think better** (mental models), **live better** (habits), and
**earn better** (a money spine). Voice is punchy and useful; quotes are real and
author-attributed. (Pivoted in place from the earlier "Calm Money Daily" finance
page — same pipeline, new niche.)

## Status

**Live posting pipeline built and verified in DRY_RUN.** Foundation, generation,
compliance gate, image rendering, Facebook publisher, brief seeding, and the
schedule-aware runner all work end-to-end. Hosted on a Windows PC: Task
Scheduler runs `run.bat` at each posting time. The live Gemini research layer
(autonomous topics) and the analytics/feedback loop are the remaining pieces;
until research is built, topics come from the seeded mock briefs.

To go live you need a `GEMINI_API_KEY` (post quality) and `FB_PAGE_ID` +
`FB_PAGE_ACCESS_TOKEN` (publishing). Without keys, the pipeline still runs in
DRY_RUN using a built-in offline writer + a regex-only compliance check.

## Stack

- **LLM:** Gemini via `google-genai` — `gemini-2.5-flash` (quotes, lists),
  `gemini-2.5-pro` (mini-blog anchor, gated behind `MINIBLOG_ALLOW_PRO` for
  free-tier accounts), `gemini-2.5-flash-lite` (compliance judge).
- **Images:** Pillow, with Lora / Inter / Playfair Display (all SIL OFL).
- **DB:** SQLite (`data/calm_money.db`), no server.
- **Scheduler:** APScheduler + pytz.
- **Publishing:** Facebook Graph API via `requests`.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env                                # then fill in keys
python db.py                                         # create the SQLite schema
```

`.env` ships as placeholders. On a free Gemini account, leave
`MINIBLOG_ALLOW_PRO=0` and `RESEARCH_USE_GROUNDING` may need to be `0` if
grounding quota is unavailable.

```bash
python get_fonts.py     # download Lora / Playfair / Inter into images/fonts/
python db.py            # create the SQLite schema
python seed_briefs.py   # seed the topic queue with starter briefs
python run_research.py  # (optional) top up the queue with fresh researched briefs
```

## Research layer (autonomous topics)

`run_research.py` calls Gemini with Google Search grounding to produce fresh
topic briefs, de-duplicates them against the last 30 days of titles, and inserts
them into the queue. Grounding and structured output can't be combined, so the
output is parsed as raw JSON and validated. On the free tier, set
`RESEARCH_USE_GROUNDING=0` (it also auto-falls-back to an ungrounded call if a
grounded one fails — ungrounded source URLs are less trustworthy, so sanity-check
with `--verify`).

```bash
python run_research.py --dry --verify   # preview briefs + HTTP-check sources, no insert
python run_research.py -n 8             # generate and insert 8 briefs
```

Schedule `research.bat` twice daily (2 PM and 10 PM Dhaka) so the queue stays
full ahead of the posting slots.

## Running it (Windows PC)

The system posts whichever slot is **due now**. `run.bat` calls `run_due.py`,
which checks today's four US-Eastern slots and publishes any that have arrived
and aren't already posted (a catch-up window covers a PC that was asleep).

```bat
run.bat                 :: post any due-but-unposted slot now
run.bat --list          :: show today's slots and their status
run.bat --slot quote    :: force one format now (manual test)
```

Set `DRY_RUN=1` in `.env` to render + stage locally (into
`data/generated_images/dry_run/`) without calling Facebook — recommended for the
first runs.

### Schedule it with Task Scheduler

Create four daily triggers calling `run.bat`, at the **Dhaka-local** equivalents
of the US-Eastern slots. Because `run_due.py` figures out the format from the
clock, every trigger runs the same command:

| US ET | Dhaka time | Format (auto-selected) |
|-------|-----------|------------------------|
| 7:00 AM | 6:00 PM | quote |
| 12:30 PM | 11:30 PM | list |
| 6:00 PM | 5:00 AM (next day) | mini-blog |
| 9:00 PM | 8:00 AM (next day) | list |

For each: Task Scheduler → Create Task → Trigger *Daily* at the Dhaka time →
Action *Start a program* → `run.bat` (Start in: the project folder). Tick
"Run whether user is logged on or not." The PC must be awake at trigger time;
if it sleeps through one, the next run within the catch-up window still posts it.
(Note ET↔Dhaka shifts by an hour during US daylight-saving changes.)

## Architecture

```
Research (twice daily, Gemini + Google Search grounding)
   → research_briefs table
   → Content Generator (structured output per format)
   → Compliance & Voice Gate (regex pre-filter + LLM judge)
   → Image Composer (Pillow + brand templates)
   → posts table (scheduled_at)
   → Scheduler & Publisher (APScheduler + Facebook Graph API)
   → Analytics Collector (Graph API /insights)
   → performance feedback loop → weights well selection
```

Key invariants:

- **Config is the single source of truth** (`config.py`). Env vars are read only
  there, via `_env()` which treats empty/whitespace as unset.
- **All timestamps stored UTC.** Convert only at the edges.
- **Grounding and `response_schema` are mutually exclusive** — research grounds
  and parses JSON by hand; generators use structured output from grounded briefs.
- **Never crash on a Gemini failure** — log, alert, continue.
- **Idempotent publishing** keyed on the Facebook post ID.
- **Deterministic image rendering** — same content always yields the same image.
- **Stoic references are paraphrase only** — never fabricated direct quotes.

## Posting schedule (US Eastern)

| ET | Dhaka | Format |
|----|-------|--------|
| 7:00 AM | 6:00 PM | Quote |
| 12:30 PM | 11:30 PM | List |
| 6:00 PM | 5:00 AM next day | Mini-blog |
| 9:00 PM | 8:00 AM next day | List |

## Content wells

`daily_discipline`, `frugal_frameworks`, `wealth_psychology`, `stoic_money`,
`common_mistakes`, `long_game`.

## Build sequence

1. **Foundation** — structure, `db.py`, `schemas.py`, prompts. ✅ *done*
2. **Generation** — three format generators + compliance gate. ✅ *done*
   (`generate_review.py` produces a 30-post voice-review file when you want it.)
4. **Images** — Pillow title cards per format/template. ✅ *done*
5. **Publishing** — Facebook Graph API photo post with retry/backoff. ✅ *done*
6. **Orchestration** — `run_due.py` + `run.bat`, schedule-aware, idempotent. ✅ *done*
3. **Research** — grounded Gemini brief generation + dedup. ✅ *done*
   (`run_research.py` / `research.bat`)
7. **Analytics & feedback** — daily insights + per-well/format/time weighting. *(deferred)*
8. **Hardening** — rotating logs (daily, 30 days), Telegram alerts, flag-file
   kill switch. ✅ *done* (systemd N/A — Task Scheduler is the process manager.)

## Operations (Phase 8)

- **Logs** rotate at midnight UTC into `logs/`, keeping 30 days
  (`calm_money.log`, `calm_money.log.2026-06-21`, ...).
- **Alerts**: set `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` and any ERROR-level
  event (publish failure, research failure, a slot that can't produce a
  compliant post) is sent to Telegram automatically. Unset = silent.
- **Kill switch / pause publishing**: create the flag file to pause, delete to
  resume — no restart or `.env` edit needed:
  ```bat
  type nul > data\KILL_SWITCH     :: pause
  del data\KILL_SWITCH            :: resume
  ```
  (Or set `KILL_SWITCH=1` in `.env`.) While paused, runs still generate and
  render but refuse to publish.

## Layout

```
config.py        schemas.py        db.py
prompts/         research/         generation/
images/          publishing/       analytics/
scheduler.py     tests/            data/   logs/
```
