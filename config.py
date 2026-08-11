"""Central configuration — the single source of truth for Calm Money Daily.

Every environment variable is read here and nowhere else. The rest of the
codebase imports constants from this module rather than touching os.environ.

`_env()` treats empty/whitespace as unset so that a blank value in .env (or a
shell that exports an empty string) falls back to the coded default instead of
silently blanking out a setting.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

PROMPTS_DIR = BASE_DIR / "prompts"
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = BASE_DIR / "images"
FONTS_DIR = IMAGES_DIR / "fonts"
BACKGROUNDS_DIR = IMAGES_DIR / "backgrounds"
GENERATED_IMAGES_DIR = DATA_DIR / "generated_images"
LOGS_DIR = BASE_DIR / "logs"


def _env(key: str, default: str = "") -> str:
    """Read an env var, treating empty/whitespace-only as unset.

    GitHub-Actions-style undefined vars resolve to "" rather than being absent,
    so a plain os.getenv(key, default) would not fall back. This does.
    """
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip()


def _env_bool(key: str, default: bool = False) -> bool:
    val = _env(key, "1" if default else "0").lower()
    return val in ("1", "true", "yes", "on")


def _env_path(key: str, default: Path) -> Path:
    raw = _env(key)
    return (BASE_DIR / raw).resolve() if raw else default


# --------------------------------------------------------------------------
# Credentials
# --------------------------------------------------------------------------
GEMINI_API_KEY = _env("GEMINI_API_KEY")

FB_PAGE_ID = _env("FB_PAGE_ID")
FB_PAGE_ACCESS_TOKEN = _env("FB_PAGE_ACCESS_TOKEN")
FB_GRAPH_VERSION = _env("FB_GRAPH_VERSION", "v21.0")

TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID")

# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------
SQLITE_PATH = _env_path("SQLITE_PATH", DATA_DIR / "calm_money.db")
LOG_PATH = _env_path("LOG_PATH", LOGS_DIR / "calm_money.log")

# --------------------------------------------------------------------------
# Timezones
# --------------------------------------------------------------------------
TIMEZONE_DHAKA = _env("TIMEZONE_DHAKA", "Asia/Dhaka")
TIMEZONE_TARGET = _env("TIMEZONE_TARGET", "America/New_York")

# --------------------------------------------------------------------------
# Gemini model routing
# --------------------------------------------------------------------------
# Routine work (quotes, lists) and the compliance judge are flash / flash-lite.
# The mini-blog anchor *wants* pro, but pro and Google Search grounding are not
# reliably available on the free tier, so both are gated behind flags that
# default to the safe (flash / ungrounded) path.
MODEL_FLASH = _env("MODEL_FLASH", "gemini-2.5-flash")
MODEL_PRO = _env("MODEL_PRO", "gemini-2.5-pro")
MODEL_LITE = _env("MODEL_LITE", "gemini-2.5-flash-lite")

MINIBLOG_ALLOW_PRO = _env_bool("MINIBLOG_ALLOW_PRO", False)
RESEARCH_USE_GROUNDING = _env_bool("RESEARCH_USE_GROUNDING", True)

# How many briefs to request per research run, and how many days of recent
# brief titles to show the model (and filter against) for de-duplication.
RESEARCH_BRIEFS_PER_RUN = int(_env("RESEARCH_BRIEFS_PER_RUN", "6"))
RESEARCH_DEDUP_DAYS = int(_env("RESEARCH_DEDUP_DAYS", "30"))

# Thinking models truncate JSON mid-output at low token caps; keep this high.
MAX_OUTPUT_TOKENS = 8192

# Generation is creative; the judge must be deterministic.
GENERATION_TEMPERATURE = 0.8
JUDGE_TEMPERATURE = 0.0


def miniblog_model() -> str:
    """The model used for the daily mini-blog anchor, honoring the free-tier gate."""
    return MODEL_PRO if MINIBLOG_ALLOW_PRO else MODEL_FLASH


# --------------------------------------------------------------------------
# Operational flags
# --------------------------------------------------------------------------
KILL_SWITCH = _env_bool("KILL_SWITCH", False)
# A flag file is the easiest way to pause publishing on a running host: create
# the file to pause, delete it to resume — no .env edit or restart needed.
KILL_SWITCH_FILE = _env_path("KILL_SWITCH_FILE", DATA_DIR / "KILL_SWITCH")
DRY_RUN = _env_bool("DRY_RUN", False)


def kill_switch_active() -> bool:
    """True if publishing is paused, via the env var or the flag file."""
    return KILL_SWITCH or KILL_SWITCH_FILE.exists()

# --------------------------------------------------------------------------
# Content wells — used by the research layer and the generator
# --------------------------------------------------------------------------
WELLS: dict[str, str] = {
    "book_lessons": "distilled lessons from ONE specific bestselling non-fiction book (the flagship format; carries the book cover)",
    "habits_systems": "small habits, routines, systems, defaults, daily discipline",
    "mental_models": "thinking tools, frameworks, and models for better decisions",
    "money_psychology": "wealth mindset, patience, behavior with money (the money spine)",
    "clear_thinking": "avoiding bias, focus, judgment, and clear decision-making",
    "timeless_wisdom": "philosophy and enduring principles for living and working well",
}
WELL_IDS = tuple(WELLS.keys())

# --------------------------------------------------------------------------
# Posting schedule — times are in TIMEZONE_TARGET (US Eastern), the audience clock.
# (hour, minute, format_type). The scheduler converts these to triggers.
# --------------------------------------------------------------------------
# Balanced daily mix: one book summary, one list, one quote, one mini-blog.
POSTING_SLOTS: tuple[tuple[int, int, str], ...] = (
    (7, 0, "book_summary"),
    (12, 30, "list"),
    (18, 0, "quote"),
    (21, 0, "mini_blog"),
)

# Research runs twice daily, in Dhaka local time.
RESEARCH_SLOTS_DHAKA: tuple[tuple[int, int], ...] = (
    (14, 0),
    (22, 0),
)

FORMAT_TYPES = ("quote", "mini_blog", "list", "book_summary")

# --------------------------------------------------------------------------
# Brand
# --------------------------------------------------------------------------
BRAND_NAME = "Compound Wisdom"

# Banned phrases — the regex pre-filter in compliance.py uses this list as the
# source of truth so the judge and the cheap pre-filter never drift apart.
# Anti-scam / advertiser-safety only (the calm-tone bans were dropped for this
# broader self-improvement niche).
BANNED_PHRASES: tuple[str, ...] = (
    "guaranteed return",
    "get rich quick",
    "double your money",
    "secret to wealth",
    "buy now",
    "limited time",
    "act now",
    "make money fast",
    "financial freedom guaranteed",
)


# --------------------------------------------------------------------------
# Reels (daily value video)
# --------------------------------------------------------------------------
PEXELS_API_KEY = _env("PEXELS_API_KEY")
EDGE_TTS_VOICE = _env("EDGE_TTS_VOICE", "en-US-AndrewNeural")
REELS_DIR = DATA_DIR / "reels"
MUSIC_DIR = BASE_DIR / "assets" / "music"
# Reel slots per day, in TIMEZONE_TARGET (US Eastern). Reels are the discovery
# engine, so we run two/day. Each slot is its own idempotency key.
REEL_SLOTS = ((11, 0), (19, 0))
REEL_MUSIC_VOLUME = float(_env("REEL_MUSIC_VOLUME", "0.12"))
REEL_TARGET_SECONDS = float(_env("REEL_TARGET_SECONDS", "40"))


def require(*keys: str) -> None:
    """Raise if any named config constant is empty. Call at the edges that need it."""
    missing = [k for k in keys if not globals().get(k)]
    if missing:
        raise RuntimeError(
            f"Missing required configuration: {', '.join(missing)}. "
            f"Set them in {BASE_DIR / '.env'}."
        )
