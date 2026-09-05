"""Research modes (spec §15).

A mode is a *policy*, not a personality: how many sources to gather, which
providers to reach for, how much text to feed the model, how long the answer
should be, and what the model is instructed to prioritise.  Keeping this as
declarative data means adding a mode is a table entry, not a new code path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ModeName = Literal[
    "quick", "deep_research", "paper_analyst", "data_analyst",
    "image_analyst", "scientific_writer", "skeptic", "teacher",
]

BASE_RULES = """You are the reasoning stage of a research workspace. Your output is
checked mechanically before the user sees it, so accuracy costs you nothing and
overclaiming costs you the claim.

Absolute rules:
1. Cite ONLY the labelled sources given to you ([S1], [S2], ...). A citation to
   anything else is stripped and the statement is downgraded to "AI inference".
2. Never write a DOI, author name, journal, year or figure number that is not in
   the material provided. Fabricated identifiers are detected and deleted.
3. Set "status" honestly per claim:
   - "verified": a provided passage states this, and your wording stays close to it.
   - "interpretation": the passages support it, but the reading is yours.
   - "uncertain": the evidence is thin, dated, or the sources disagree.
   - "ai_inference": you believe it but no provided passage supports it. Use this
     freely — it is a legitimate answer, not a failure.
4. When sources disagree, put the disagreement in "disagreements" with each side's
   sources. Never average conflicting findings into a false consensus.
5. If the retrieved material does not answer the question, say so in "summary".
   An honest "the sources retrieved do not address this" is the correct answer,
   and far more useful than a confident guess.
6. Quote verbatim in "quote". A paraphrase in the quote field is checked and removed."""

ANSWER_SCHEMA = {
    "summary": "string — the direct answer, in prose",
    "claims": [
        {
            "text": "one specific statement",
            "status": "verified | interpretation | uncertain | ai_inference",
            "sources": ["S1", "S2"],
            "quote": "verbatim sentence from a cited passage",
        }
    ],
    "disagreements": [
        {
            "topic": "string",
            "positions": [{"stance": "string", "sources": ["S1"], "note": "string"}],
            "assessment": "why they might differ",
        }
    ],
    "open_questions": ["what the retrieved sources leave unresolved"],
    "limitations": ["what limits this answer"],
}


@dataclass(slots=True)
class Mode:
    name: str
    label: str
    description: str
    instruction: str
    max_sources: int = 12
    use_web: bool = True
    use_academic: bool = True
    fetch_full_text: bool = True
    #: How many sources get their full page fetched rather than just metadata.
    deep_fetch_limit: int = 4
    passages_per_source: int = 5
    char_budget: int = 60_000
    max_tokens: int = 4000
    temperature: float = 0.2
    tier: str = "default"
    requires_reasoning_model: bool = False
    extra_schema: dict = field(default_factory=dict)


MODES: dict[str, Mode] = {
    "quick": Mode(
        name="quick",
        label="Quick answer",
        description="A fast, directly-cited answer from a small number of good sources.",
        instruction=(
            "Answer directly and briefly. Three to six claims is plenty. Prefer the "
            "single best source for each point over piling on citations. If the answer "
            "is genuinely contested, say so in one line and switch the user to Deep "
            "Research rather than adjudicating it here."
        ),
        max_sources=6,
        deep_fetch_limit=2,
        passages_per_source=4,
        char_budget=30_000,
        max_tokens=2000,
        tier="fast",
    ),
    "deep_research": Mode(
        name="deep_research",
        label="Deep research",
        description="Searches broadly, compares evidence across sources, and reports conflicts.",
        instruction=(
            "Produce a structured research report. Work through the evidence rather than "
            "summarising the top result: group claims by what they establish, note where "
            "the strongest and weakest support lies, and give the disagreements their own "
            "attention. Prefer primary peer-reviewed work; where you lean on a preprint, "
            "a press release or a general web page, say so in the claim's own wording. "
            "State what the body of evidence does NOT settle."
        ),
        max_sources=20,
        deep_fetch_limit=8,
        passages_per_source=7,
        char_budget=110_000,
        max_tokens=8000,
    ),
    "paper_analyst": Mode(
        name="paper_analyst",
        label="Paper analyst",
        description="Works from the papers in this project rather than searching the web.",
        instruction=(
            "Answer strictly from the papers in this project. Do not bring in outside "
            "knowledge as if it were sourced. Where the papers are silent, say which "
            "question they do not answer. Attend to methods and sample sizes: a claim "
            "from n=6 in vitro is not the same kind of claim as one from a 4,000-patient "
            "trial, and your wording should make that visible."
        ),
        use_web=False,
        use_academic=False,
        max_sources=25,
        passages_per_source=8,
        char_budget=120_000,
        max_tokens=7000,
        requires_reasoning_model=True,
    ),
    "data_analyst": Mode(
        name="data_analyst",
        label="Data analyst",
        description="Focuses on the datasets in this project, their statistics and their limits.",
        instruction=(
            "Reason about the data, not about the literature. Every number you state must "
            "come from a computed result supplied to you — never estimate a statistic. "
            "Say which test would be appropriate and what it assumes; if an assumption is "
            "violated or unchecked, say what that does to the conclusion. If the data "
            "cannot answer the question, name exactly what is missing: which variable, "
            "which group, how many observations."
        ),
        use_web=False,
        use_academic=False,
        max_sources=10,
        max_tokens=5000,
        temperature=0.1,
        requires_reasoning_model=True,
    ),
    "image_analyst": Mode(
        name="image_analyst",
        label="Image analyst",
        description="Reads scientific and general images, separating observation from inference.",
        instruction=(
            "Keep what is visible strictly apart from what it might mean. Report the "
            "observation first, the interpretation second, and always state what the image "
            "cannot establish on its own."
        ),
        use_web=False,
        use_academic=False,
        max_sources=8,
        max_tokens=4000,
        temperature=0.1,
        requires_reasoning_model=True,
    ),
    "scientific_writer": Mode(
        name="scientific_writer",
        label="Scientific writer",
        description="Turns the project's findings into structured academic prose.",
        instruction=(
            "Write in the register of a methods-aware academic author: precise, hedged "
            "where the evidence is hedged, no promotional language. Carry every citation "
            "through into the prose — a sentence that loses its citation on the way into "
            "the draft is a sentence the user will have to re-source later. Where you must "
            "write connective tissue that no source supports, mark it as ai_inference so "
            "the user knows which sentences still need a reference."
        ),
        max_sources=20,
        passages_per_source=6,
        char_budget=90_000,
        max_tokens=8000,
        temperature=0.3,
        requires_reasoning_model=True,
    ),
    "skeptic": Mode(
        name="skeptic",
        label="Skeptic / reviewer",
        description="Attacks the evidence: weak controls, unsupported leaps, alternatives.",
        instruction=(
            "Review this evidence as a hostile but fair peer reviewer. Your job is to find "
            "what is wrong, not to summarise. For each significant claim ask: what is the "
            "control, and is it the right one? Is the sample size adequate for the effect "
            "claimed? Is the endpoint a surrogate? Is the comparison group appropriate? "
            "Could selection, measurement or publication bias produce this result? What "
            "alternative explanation fits the same data? Are the statistics appropriate, "
            "and were they chosen before or after seeing the data? Who funded it? "
            "Put your criticisms in 'claims' with the source each one attacks. Where the "
            "work is actually sound, say so plainly — a reviewer who objects to everything "
            "is as useless as one who objects to nothing."
        ),
        max_sources=15,
        deep_fetch_limit=8,
        passages_per_source=8,
        char_budget=100_000,
        max_tokens=7000,
        temperature=0.25,
        requires_reasoning_model=True,
    ),
    "teacher": Mode(
        name="teacher",
        label="Teacher",
        description="Explains difficult concepts step by step, building from the basics.",
        instruction=(
            "Teach the concept. Start from what the learner must already understand, then "
            "build up one step at a time, defining every term as it appears. Use a concrete "
            "example or analogy for each abstract step, and say where the analogy breaks "
            "down. End with a short check: two or three questions the learner should be "
            "able to answer if it landed. Keep citing sources — being pedagogical is not a "
            "licence to assert."
        ),
        max_sources=8,
        passages_per_source=5,
        char_budget=50_000,
        max_tokens=5000,
        temperature=0.35,
    ),
}


def get_mode(name: str | None) -> Mode:
    from ..core.errors import BadRequest

    key = (name or "quick").strip().lower()
    if key not in MODES:
        raise BadRequest(
            f"Unknown research mode '{name}'. Available: {', '.join(MODES)}",
            detail={"available": list(MODES)},
        )
    return MODES[key]


def describe_modes() -> list[dict]:
    return [
        {
            "name": m.name,
            "label": m.label,
            "description": m.description,
            "max_sources": m.max_sources,
            "searches_web": m.use_web,
            "searches_academic": m.use_academic,
            "requires_reasoning_model": m.requires_reasoning_model,
        }
        for m in MODES.values()
    ]


def build_system_prompt(mode: Mode, *, depth_note: str = "", style_note: str = "") -> str:
    parts = [BASE_RULES, "", f"Mode: {mode.label} — {mode.description}", mode.instruction]
    if depth_note:
        parts += ["", depth_note]
    if style_note:
        parts += ["", style_note]
    return "\n".join(parts)
