"""Curated pool of bestseller + semi-bestseller non-fiction, plus cover fetch.

Covers come from Open Library (free, no API key, ~500px). fetch_cover() caches
to data/covers/ and returns a local path, or None if no cover is found (the
composer then falls back to a text-only book card).

The BOOKS pool spans the page's themes — habits/focus, money, thinking/behavior,
business, communication, and philosophy/self — deliberately mixing famous titles
with strong lesser-known ones so content never repeats the same five books.
"""
from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import Optional

import requests
from PIL import Image

import config

log = logging.getLogger("calm_money.books")

COVERS_DIR = config.DATA_DIR / "covers"

# (title, author) — kept advertiser-friendly (no profanity in titles).
BOOKS: list[tuple[str, str]] = [
    # Habits / focus / productivity
    ("Atomic Habits", "James Clear"),
    ("The Power of Habit", "Charles Duhigg"),
    ("Deep Work", "Cal Newport"),
    ("Digital Minimalism", "Cal Newport"),
    ("Essentialism", "Greg McKeown"),
    ("The One Thing", "Gary Keller"),
    ("Tiny Habits", "BJ Fogg"),
    ("Getting Things Done", "David Allen"),
    ("Make Time", "Jake Knapp"),
    ("Four Thousand Weeks", "Oliver Burkeman"),
    ("The Compound Effect", "Darren Hardy"),
    ("The Slight Edge", "Jeff Olson"),
    ("Indistractable", "Nir Eyal"),
    ("Hyperfocus", "Chris Bailey"),
    ("Eat That Frog", "Brian Tracy"),
    ("The 7 Habits of Highly Effective People", "Stephen Covey"),
    ("The 5 AM Club", "Robin Sharma"),
    # Money / wealth
    ("The Psychology of Money", "Morgan Housel"),
    ("Same as Ever", "Morgan Housel"),
    ("The Richest Man in Babylon", "George Clason"),
    ("The Millionaire Next Door", "Thomas Stanley"),
    ("I Will Teach You to Be Rich", "Ramit Sethi"),
    ("Your Money or Your Life", "Vicki Robin"),
    ("The Simple Path to Wealth", "JL Collins"),
    ("Rich Dad Poor Dad", "Robert Kiyosaki"),
    ("The Intelligent Investor", "Benjamin Graham"),
    ("The Little Book of Common Sense Investing", "John Bogle"),
    ("Die With Zero", "Bill Perkins"),
    ("The Total Money Makeover", "Dave Ramsey"),
    ("Think and Grow Rich", "Napoleon Hill"),
    ("A Random Walk Down Wall Street", "Burton Malkiel"),
    # Thinking / behavior / decisions
    ("Thinking, Fast and Slow", "Daniel Kahneman"),
    ("Influence", "Robert Cialdini"),
    ("Predictably Irrational", "Dan Ariely"),
    ("Nudge", "Richard Thaler"),
    ("Thinking in Bets", "Annie Duke"),
    ("The Art of Thinking Clearly", "Rolf Dobelli"),
    ("Superforecasting", "Philip Tetlock"),
    ("Poor Charlie's Almanack", "Charles Munger"),
    ("Fooled by Randomness", "Nassim Taleb"),
    ("The Black Swan", "Nassim Taleb"),
    ("Antifragile", "Nassim Taleb"),
    ("Skin in the Game", "Nassim Taleb"),
    ("Clear Thinking", "Shane Parrish"),
    ("Range", "David Epstein"),
    ("Mindset", "Carol Dweck"),
    ("Grit", "Angela Duckworth"),
    ("Drive", "Daniel Pink"),
    # Business / strategy
    ("Good to Great", "Jim Collins"),
    ("Zero to One", "Peter Thiel"),
    ("The Lean Startup", "Eric Ries"),
    ("Start With Why", "Simon Sinek"),
    ("The E-Myth Revisited", "Michael Gerber"),
    ("Shoe Dog", "Phil Knight"),
    ("Principles", "Ray Dalio"),
    ("The Almanack of Naval Ravikant", "Eric Jorgenson"),
    ("Measure What Matters", "John Doerr"),
    ("The Hard Thing About Hard Things", "Ben Horowitz"),
    ("Built to Last", "Jim Collins"),
    ("The Innovator's Dilemma", "Clayton Christensen"),
    # Communication / influence / sales
    ("How to Win Friends and Influence People", "Dale Carnegie"),
    ("Never Split the Difference", "Chris Voss"),
    ("To Sell Is Human", "Daniel Pink"),
    ("Made to Stick", "Chip Heath"),
    ("Contagious", "Jonah Berger"),
    ("Crucial Conversations", "Kerry Patterson"),
    ("Pre-Suasion", "Robert Cialdini"),
    ("Pitch Anything", "Oren Klaff"),
    # Philosophy / self / wellbeing
    ("Man's Search for Meaning", "Viktor Frankl"),
    ("Meditations", "Marcus Aurelius"),
    ("The Daily Stoic", "Ryan Holiday"),
    ("The Obstacle Is the Way", "Ryan Holiday"),
    ("Ego Is the Enemy", "Ryan Holiday"),
    ("Stillness Is the Key", "Ryan Holiday"),
    ("12 Rules for Life", "Jordan Peterson"),
    ("The War of Art", "Steven Pressfield"),
    ("Ikigai", "Hector Garcia"),
    ("Flow", "Mihaly Csikszentmihalyi"),
    ("The Happiness Hypothesis", "Jonathan Haidt"),
    ("Stumbling on Happiness", "Daniel Gilbert"),
    ("Sapiens", "Yuval Noah Harari"),
    # Learning / mastery
    ("Ultralearning", "Scott Young"),
    ("Make It Stick", "Peter Brown"),
    ("Peak", "Anders Ericsson"),
    ("Outliers", "Malcolm Gladwell"),
    ("Mastery", "Robert Greene"),
    ("The Talent Code", "Daniel Coyle"),
]


def all_books() -> list[tuple[str, str]]:
    return list(BOOKS)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def fetch_cover(title: str, author: str = "") -> Optional[Path]:
    """Return a local path to the book's cover (cached), or None if unavailable."""
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    path = COVERS_DIR / f"{_slug(title)}.jpg"
    if path.exists() and path.stat().st_size > 5000:
        return path
    try:
        params = {"title": title, "limit": 1}
        if author:
            params["author"] = author
        data = requests.get("https://openlibrary.org/search.json", params=params, timeout=20).json()
        docs = data.get("docs", [])
        if not docs or not docs[0].get("cover_i"):
            return None
        cover_id = docs[0]["cover_i"]
        url = f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"
        content = requests.get(url, timeout=20).content
        Image.open(io.BytesIO(content)).verify()  # reject HTML/placeholder bytes
        path.write_bytes(content)
        return path
    except Exception as e:
        log.warning("cover fetch failed for %r: %s", title, e)
        return None
