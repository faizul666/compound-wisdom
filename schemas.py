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


class QuotePost(BaseModel):
    quote_text: str = Field(description="15-25 words, original wisdom in brand voice")
    attribution: Literal["— Calm Money Daily"]
    image_background_template: QuoteTemplate
    caption_body: str = Field(description="200-400 words, reflective expansion")
    closing_question: str


class MiniBlogPost(BaseModel):
    headline: str = Field(description="6-12 words, sentence case")
    headline_image_template: MiniBlogTemplate
    caption_body: str = Field(description="300-600 words, hook + 3-4 paragraphs + close")
    closing_question: str


class ListItem(BaseModel):
    name: str
    explanation: str


class ListPost(BaseModel):
    title: str
    # Plain int, not Literal[5, 10]: Gemini's response_schema only supports
    # string enums, so an int Literal breaks schema construction. The
    # "exactly 5 or 10" rule is enforced in the generator's _post_validate.
    count: int = Field(description="exactly 5 or 10")
    list_image_template: ListTemplate
    intro_line: str
    items: list[ListItem]
    closing_line: str


# --------------------------------------------------------------------------
# Research
# --------------------------------------------------------------------------
WellId = Literal[
    "daily_discipline",
    "frugal_frameworks",
    "wealth_psychology",
    "stoic_money",
    "common_mistakes",
    "long_game",
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
    suggested_format: Literal["quote", "mini_blog", "list"]
    suggested_list_count: Optional[Literal[5, 10]] = None
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
