"""Pydantic models — the contract between every stage of the pipeline.

The content models (QuotePost, MiniBlogPost, ListPost) double as Gemini
`response_schema` targets for structured generation. ResearchBrief* are parsed
by hand from grounded output (grounding and response_schema are mutually
exclusive). ComplianceResult is the judge's verdict.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------
# Content formats
# --------------------------------------------------------------------------
QuoteTemplate = Literal[
    "warm_gradient", "parchment", "minimal_photo", "branded_solid", "serif_card"
]
MiniBlogTemplate = Literal[
    "bold_sans", "editorial_serif", "warm_serif", "minimal_photo_overlay"
]
ListTemplate = Literal[
    "numbered_bold", "serif_list_card", "warm_gradient_list", "minimal_dark"
]
BookTemplate = Literal["cover_left", "cover_spotlight", "cover_top"]


class QuotePost(BaseModel):
    quote_text: str = Field(description="a real, verifiable quote from a book/author, 8-30 words")
    attribution: str = Field(description="the real author and source, e.g. '— James Clear, Atomic Habits'")
    image_background_template: QuoteTemplate
    caption_body: str = Field(description="150-320 words expanding on the idea")
    closing_question: str
    hashtags: list[str] = Field(description="3-5 specific long-tail hashtags WITHOUT the # (e.g. jamesclear, atomichabits, moneymindset)")


class MiniBlogPost(BaseModel):
    headline: str = Field(description="6-12 words, framed as a question or a claim that matches how people search, e.g. 'Why Willpower Fails and Systems Don't'")
    headline_image_template: MiniBlogTemplate
    caption_hook: str = Field(description="the caption's first line (<=125 chars): a searchable claim + a concrete entity/number, NOT a soft intro")
    caption_body: str = Field(description="300-600 words, hook + 3-4 paragraphs + close")
    closing_question: str
    hashtags: list[str] = Field(description="3-5 specific long-tail hashtags WITHOUT the # (e.g. deepwork, focus, productivity)")


class ListItem(BaseModel):
    name: str
    explanation: str


class ListPost(BaseModel):
    title: str = Field(description="topic noun FIRST, number second, e.g. 'Mental Models: 7 That Change How You Decide' (front-load the searchable term, not the number)")
    # Plain int, not Literal[5, 10]: Gemini's response_schema only supports
    # string enums, so an int Literal breaks schema construction. The
    # "exactly 5 or 10" rule is enforced in the generator's _post_validate.
    count: int = Field(description="exactly 5, 7, or 10")
    list_image_template: ListTemplate
    caption_hook: str = Field(description="the caption's first line (<=125 chars): a searchable claim naming the topic, NOT 'Here are 7...'")
    intro_line: str
    items: list[ListItem]
    closing_line: str
    hashtags: list[str] = Field(description="3-5 specific long-tail hashtags WITHOUT the # (e.g. mentalmodels, decisionmaking, munger)")


class BookLesson(BaseModel):
    lesson: str = Field(description="the takeaway as a short punchy phrase")
    detail: str = Field(description="1-2 sentences making it concrete")


class BookSummaryPost(BaseModel):
    book_title: str = Field(description="exact book title, so its cover can be fetched")
    book_author: str = Field(description="the author's name")
    publication_year: str = Field(description="the book's publication year, e.g. '2018'")
    count: int = Field(description="number of lessons, exactly 5 or 7")
    headline: str = Field(description="book TITLE first, then the count, e.g. 'Atomic Habits: 7 Lessons' (the title is the search term)")
    book_image_template: BookTemplate
    caption_hook: str = Field(description="the caption's first line (<=125 chars): a searchable claim naming the book, e.g. 'Atomic Habits sold 20M copies. These 7 ideas are why.'")
    intro_line: str
    lessons: list["BookLesson"]
    closing_line: str
    hashtags: list[str] = Field(description="3-5 specific long-tail hashtags WITHOUT the # (e.g. atomichabits, jamesclear, habitstacking, booksummary)")


class ReelScript(BaseModel):
    """A value reel, structured as 5 timed beats (~25s). Not a book promo, but it
    DOES cite real research (name + number + year) — that's the differentiator."""
    hook_text: str = Field(description="on-screen hook, 4-8 words, that NAMES the specific claim (never 'this'/'the secret'/'do this')")
    hook_claim: str = Field(description="spoken 0-2s: the concrete surprising claim, no setup, starting on a number or hard word (never 'So'/'The')")
    evidence: str = Field(description="spoken 2-5s: a REAL specific — a named person or study, a number, and a year; add a short caveat if apt")
    mechanism: str = Field(description="spoken 5-15s: WHY it's true — the actual mechanism (this is the meat)")
    action: str = Field(description="spoken 15-22s: ONE specific action, stated as a sentence someone could do tomorrow")
    question: str = Field(description="spoken 22-25s: a binary/answerable question that invites a comment (e.g. 'Which one are you?')")
    key_stat: str = Field(description="the single headline number or name to show BIG on screen, e.g. '66 DAYS' or 'MUNGER'")
    source_note: str = Field(description="the citation for the caption, e.g. 'Lally, University College London, 2009'")
    broll_keywords: list[str] = Field(description="5-8 CONCRETE visual nouns that literally illustrate the claim/numbers (e.g. 'calendar pages flipping', 'stack of coins'); NO cliches")
    caption: str = Field(description="the Facebook caption: hook line + the specific stat + a soft CTA like 'Save this.'")
    hashtags: list[str] = Field(description="exactly 5 broad self-improvement hashtags, without the # sign")

    def beats(self) -> list[str]:
        return [self.hook_claim, self.evidence, self.mechanism, self.action, self.question]


# --------------------------------------------------------------------------
# Research
# --------------------------------------------------------------------------
WellId = Literal[
    "book_lessons",
    "habits_systems",
    "mental_models",
    "money_psychology",
    "clear_thinking",
    "timeless_wisdom",
]


class SupportingFact(BaseModel):
    fact: str
    source_url: str
    source_name: str


class ResearchBrief(BaseModel):
    well_id: WellId
    angle_title: str
    angle_summary: str
    supporting_facts: list[SupportingFact]
    suggested_format: Literal["quote", "mini_blog", "list", "book_summary"]
    suggested_list_count: Optional[Literal[5, 7, 10]] = None
    # For book_summary / book-anchored briefs: the specific book to feature.
    book_title: Optional[str] = None
    book_author: Optional[str] = None
    evergreen: bool
    voice_compatibility_notes: str


class ResearchBriefBatch(BaseModel):
    briefs: list[ResearchBrief]


# --------------------------------------------------------------------------
# Compliance
# --------------------------------------------------------------------------
class ComplianceResult(BaseModel):
    # `pass` is a Python keyword; expose it as pass_ but accept/emit "pass".
    model_config = ConfigDict(populate_by_name=True)

    pass_: bool = Field(alias="pass")
    failed_checks: list[str]
    notes: str
