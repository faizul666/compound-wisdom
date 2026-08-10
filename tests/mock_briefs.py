"""Mock research briefs for Compound Wisdom — seed the queue before research runs.

A balanced set across the four formats (book_summary / list / quote / mini_blog)
and the six wells. Book-anchored briefs name a real book + author.
"""
from __future__ import annotations

from schemas import ResearchBrief, SupportingFact


def _brief(well, title, summary, fact, url, source, fmt, notes,
           list_count=None, book_title=None, book_author=None, evergreen=True):
    return ResearchBrief(
        well_id=well,
        angle_title=title,
        angle_summary=summary,
        supporting_facts=[SupportingFact(fact=fact, source_url=url, source_name=source)],
        suggested_format=fmt,
        suggested_list_count=list_count,
        book_title=book_title,
        book_author=book_author,
        evergreen=evergreen,
        voice_compatibility_notes=notes,
    )


_BOOK = [
    _brief("book_lessons", "The core lessons of Atomic Habits",
           "James Clear's Atomic Habits: systems over goals, 1% better, identity habits, friction.",
           "Improving 1% daily compounds to ~37x over a year; you fall to the level of your systems.",
           "https://jamesclear.com/atomic-habits", "James Clear, Atomic Habits",
           "book_summary", "5 punchy lessons; reference the book; no fabricated quotes.",
           book_title="Atomic Habits", book_author="James Clear"),
    _brief("book_lessons", "What The Psychology of Money teaches about behavior",
           "Morgan Housel: doing well with money is about behavior, not intelligence.",
           "Housel argues wealth is what you don't see; 'enough' is the key skill.",
           "https://www.morganhousel.com/", "Morgan Housel, The Psychology of Money",
           "book_summary", "7 lessons; keep the money spine; educational not advisory.",
           book_title="The Psychology of Money", book_author="Morgan Housel"),
    _brief("book_lessons", "Deep Work, distilled for people who can't focus",
           "Cal Newport: focused, distraction-free work is rare and valuable.",
           "Newport frames deep work as increasingly scarce and increasingly valuable at once.",
           "https://calnewport.com/", "Cal Newport, Deep Work",
           "book_summary", "5 lessons; practical, structure over willpower.",
           book_title="Deep Work", book_author="Cal Newport"),
    _brief("book_lessons", "How to Win Friends and Influence People in 5 ideas",
           "Dale Carnegie's timeless principles on dealing with people.",
           "Carnegie's core idea: make the other person feel important, sincerely.",
           "https://www.dalecarnegie.com/", "Dale Carnegie",
           "book_summary", "5 lessons; warm and practical; no manipulation framing.",
           book_title="How to Win Friends and Influence People", book_author="Dale Carnegie"),
]

_LIST = [
    _brief("mental_models", "Mental models that make hard decisions easier",
           "A handful of models (inversion, opportunity cost, second-order thinking) that improve judgment.",
           "Charlie Munger advocates a 'latticework' of mental models from many disciplines.",
           "https://fs.blog/mental-models/", "Farnam Street",
           "list", "Concrete everyday examples; attribute models to their thinkers.", list_count=7),
    _brief("habits_systems", "Small habits that compound over a decade",
           "Tiny, repeatable habits that get more powerful the longer they're kept.",
           "Reading 20 pages a day is ~20-30 books a year.",
           "https://jamesclear.com/", "James Clear",
           "list", "Each item small enough to start this week.", list_count=5),
    _brief("money_psychology", "Money habits of people who stay calm about it",
           "Behaviors that separate financially calm people, drawn from behavioral finance.",
           "Frequent portfolio-checking raises perceived risk without improving returns.",
           "https://www.morningstar.com/", "Morningstar",
           "list", "Educational; no specific investment advice.", list_count=5),
    _brief("clear_thinking", "Thinking traps that quietly cost you",
           "Common cognitive biases (sunk cost, confirmation, recency) and how to counter them.",
           "The sunk-cost fallacy keeps people investing in losing courses of action.",
           "https://www.behavioraleconomics.com/", "Behavioral Economics Guide",
           "list", "Name each bias plainly with a real-life example.", list_count=7),
]

_QUOTE = [
    _brief("habits_systems", "James Clear on systems vs goals",
           "Clear's point that systems, not goals, determine outcomes.",
           "'You do not rise to the level of your goals. You fall to the level of your systems.'",
           "https://jamesclear.com/atomic-habits", "James Clear, Atomic Habits",
           "quote", "Use a real Clear quote; expand usefully."),
    _brief("mental_models", "Charlie Munger on the power of waiting",
           "Munger's view that patience, not activity, builds wealth.",
           "'The big money is not in the buying and selling, but in the waiting.'",
           "https://fs.blog/charlie-munger/", "Farnam Street",
           "quote", "Real Munger quote; tie patience to everyday life."),
    _brief("timeless_wisdom", "Viktor Frankl on choosing your response",
           "Frankl's idea that freedom lies in how we respond to what happens.",
           "Man's Search for Meaning centers on choosing one's attitude in any circumstance.",
           "https://www.viktorfrankl.org/", "Viktor Frankl, Man's Search for Meaning",
           "quote", "Use a real, verifiable Frankl quote; keep it grounded."),
    _brief("money_psychology", "Naval Ravikant on long-term games",
           "Naval's principle of playing long-term games with long-term people.",
           "'Play long-term games with long-term people.'",
           "https://nav.al/", "Naval Ravikant",
           "quote", "Real Naval quote; connect to compounding."),
]

_MINIBLOG = [
    _brief("clear_thinking", "The thinking tool Charlie Munger swears by",
           "Inversion — solving problems backward by asking how you'd fail.",
           "Munger: 'All I want to know is where I'm going to die, so I'll never go there.'",
           "https://fs.blog/inversion/", "Farnam Street",
           "mini_blog", "Explain inversion with a concrete everyday example."),
    _brief("habits_systems", "Why focus is becoming a superpower",
           "Deep, undistracted work is rare and rising in value.",
           "Cal Newport argues deep work is scarce and valuable simultaneously.",
           "https://calnewport.com/", "Cal Newport, Deep Work",
           "mini_blog", "Structure over willpower; one concrete change to try."),
    _brief("money_psychology", "What an extra bit saved becomes over decades",
           "Compounding rewards patience more than intelligence.",
           "At a 7% average return, small monthly amounts grow large over 30 years via compounding.",
           "https://www.investor.gov/", "Investor.gov",
           "mini_blog", "Educational compound illustration; never promise outcomes."),
    _brief("timeless_wisdom", "The essentialist's question for a busy life",
           "Greg McKeown's disciplined pursuit of less but better.",
           "Essentialism: if it isn't a clear yes, it's a clear no.",
           "https://gregmckeown.com/", "Greg McKeown, Essentialism",
           "mini_blog", "One reframe the reader can apply this week."),
]

ALL_BRIEFS = _BOOK + _LIST + _QUOTE + _MINIBLOG


def all_briefs() -> list[ResearchBrief]:
    return list(ALL_BRIEFS)
