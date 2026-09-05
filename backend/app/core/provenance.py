"""The provenance model — the spine of the whole application.

Nothing reaches the user without travelling through these types:

    Source      where something came from (a URL, paper, PDF, video, image, dataset)
    Passage     a verbatim span *actually retrieved* from a Source
    Claim       an assertion, tagged with epistemic status and backed by Passages
    Answer      claims + reasoning trace + the conflicts we refused to hide

The invariant enforced downstream (see ``services/grounding.py``) is:
a Claim may only cite Passage ids that exist in the retrieval set for this
turn.  A model that invents ``[S7]`` when only S1..S4 were retrieved has its
citation stripped and the claim demoted to ``ai_inference``.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# --------------------------------------------------------------------------
# Epistemic status
# --------------------------------------------------------------------------
class Epistemic(str, Enum):
    """How a statement earned its place in the answer.

    Rendered distinctly in the UI so the reader never has to guess which
    sentences are grounded and which are the model talking.
    """

    VERIFIED = "verified"                # directly supported by a retrieved passage
    INTERPRETATION = "interpretation"    # reasonable reading of retrieved passages
    UNCERTAIN = "uncertain"              # sources are thin, dated, or conflicting
    AI_INFERENCE = "ai_inference"        # model reasoning, no retrieved support

    @property
    def label(self) -> str:
        return {
            Epistemic.VERIFIED: "Verified",
            Epistemic.INTERPRETATION: "Reasonable interpretation",
            Epistemic.UNCERTAIN: "Uncertain",
            Epistemic.AI_INFERENCE: "AI inference",
        }[self]


class SourceKind(str, Enum):
    WEB_PAGE = "web_page"
    JOURNAL_ARTICLE = "journal_article"
    PREPRINT = "preprint"
    BOOK = "book"
    NEWS = "news"
    GOVERNMENT = "government"
    INSTITUTIONAL = "institutional"
    DOCUMENTATION = "documentation"
    DATASET = "dataset"
    VIDEO = "video"
    IMAGE = "image"
    UPLOADED_DOCUMENT = "uploaded_document"
    NOTE = "note"
    UNKNOWN = "unknown"


class Evidentiary(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    TERTIARY = "tertiary"
    UNKNOWN = "unknown"


class Author(BaseModel):
    name: str
    given: str | None = None
    family: str | None = None
    orcid: str | None = None
    affiliation: str | None = None

    @classmethod
    def parse(cls, raw: str) -> "Author":
        raw = " ".join(raw.split())
        if "," in raw:
            family, _, given = raw.partition(",")
            return cls(name=raw, family=family.strip(), given=given.strip() or None)
        parts = raw.split()
        if len(parts) >= 2:
            return cls(name=raw, given=" ".join(parts[:-1]), family=parts[-1])
        return cls(name=raw, family=raw or None)


# --------------------------------------------------------------------------
# Passage
# --------------------------------------------------------------------------
class Passage(BaseModel):
    """A verbatim span retrieved from a Source. Never synthesised."""

    id: str = Field(default_factory=lambda: new_id("psg"))
    source_id: str
    text: str
    # Locators — whichever the medium supports.
    page: int | None = None
    section: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    start_seconds: float | None = None   # video/audio
    end_seconds: float | None = None
    score: float | None = None           # retrieval score, provider-relative

    def fingerprint(self) -> str:
        return hashlib.sha256(self.text.strip().encode("utf-8")).hexdigest()[:16]

    @property
    def locator(self) -> str:
        if self.start_seconds is not None:
            m, s = divmod(int(self.start_seconds), 60)
            h, m = divmod(m, 60)
            return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"
        if self.page is not None:
            return f"p. {self.page}"
        if self.section:
            return self.section
        return ""


# --------------------------------------------------------------------------
# Source
# --------------------------------------------------------------------------
class Source(BaseModel):
    """Everything needed to cite, judge, and re-find a piece of evidence."""

    id: str = Field(default_factory=lambda: new_id("src"))
    kind: SourceKind = SourceKind.UNKNOWN
    title: str
    url: str | None = None
    doi: str | None = None
    pmid: str | None = None
    arxiv_id: str | None = None
    isbn: str | None = None

    authors: list[Author] = Field(default_factory=list)
    container_title: str | None = None      # journal / site / publisher
    publisher: str | None = None
    site_name: str | None = None
    published: date | None = None
    accessed: date = Field(default_factory=lambda: _now().date())

    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    language: str | None = None
    license: str | None = None

    abstract: str | None = None
    is_open_access: bool | None = None
    is_peer_reviewed: bool | None = None
    retracted: bool | None = None
    cited_by_count: int | None = None
    evidentiary: Evidentiary = Evidentiary.UNKNOWN

    # Which adapter produced this record, and whether we actually read the body.
    retrieved_by: str = "unknown"
    full_text_retrieved: bool = False
    retrieval_note: str | None = None

    quality: "SourceQuality | None" = None
    passages: list[Passage] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    @property
    def year(self) -> int | None:
        return self.published.year if self.published else None

    @property
    def domain(self) -> str | None:
        if not self.url:
            return None
        from urllib.parse import urlparse

        host = urlparse(self.url).netloc.lower()
        return host[4:] if host.startswith("www.") else host or None

    def identity_key(self) -> str:
        """Used to de-duplicate the same work arriving from several providers."""
        if self.doi:
            return f"doi:{self.doi.lower()}"
        if self.pmid:
            return f"pmid:{self.pmid}"
        if self.arxiv_id:
            return f"arxiv:{self.arxiv_id.lower()}"
        if self.url:
            from urllib.parse import urlsplit, urlunsplit

            p = urlsplit(self.url)
            return "url:" + urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip("/"), "", ""))
        return "title:" + " ".join(self.title.lower().split())


class QualitySignal(BaseModel):
    """One reason a source is strong or weak, in plain language.

    Deliberately a *list* rather than a single number — a lone 0-100 score
    hides exactly the reasoning a researcher needs to audit.
    """

    dimension: str
    verdict: Literal["strong", "adequate", "weak", "unknown", "caution"]
    explanation: str
    weight: float = 1.0


class SourceQuality(BaseModel):
    tier: Literal[
        "primary_peer_reviewed",
        "peer_reviewed",
        "preprint",
        "official",
        "established_outlet",
        "general_web",
        "user_supplied",
        "unknown",
    ] = "unknown"
    signals: list[QualitySignal] = Field(default_factory=list)
    summary: str = ""
    caveats: list[str] = Field(default_factory=list)

    @property
    def strong_count(self) -> int:
        return sum(1 for s in self.signals if s.verdict == "strong")

    @property
    def weak_count(self) -> int:
        return sum(1 for s in self.signals if s.verdict in ("weak", "caution"))


Source.model_rebuild()


# --------------------------------------------------------------------------
# Claims & answers
# --------------------------------------------------------------------------
class Citation(BaseModel):
    source_id: str
    passage_ids: list[str] = Field(default_factory=list)
    quote: str | None = None
    locator: str | None = None


class Claim(BaseModel):
    id: str = Field(default_factory=lambda: new_id("clm"))
    text: str
    status: Epistemic = Epistemic.AI_INFERENCE
    citations: list[Citation] = Field(default_factory=list)
    # Populated by the verifier: why this claim carries the status it does.
    verification_note: str | None = None
    support_score: float | None = None      # lexical overlap with cited passages
    contested_by: list[str] = Field(default_factory=list)   # source ids that disagree

    @property
    def is_grounded(self) -> bool:
        return bool(self.citations) and self.status in (
            Epistemic.VERIFIED,
            Epistemic.INTERPRETATION,
        )


class Disagreement(BaseModel):
    """An explicit conflict between sources. Surfaced, never smoothed over."""

    topic: str
    positions: list["Position"] = Field(default_factory=list)
    assessment: str | None = None


class Position(BaseModel):
    stance: str
    source_ids: list[str] = Field(default_factory=list)
    note: str | None = None


Disagreement.model_rebuild()


class ReasoningStep(BaseModel):
    """One entry in the 'How did you reach this conclusion?' trace."""

    stage: str
    detail: str
    data: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=_now)
    duration_ms: int | None = None


class Trace(BaseModel):
    """The inspectable record of a research turn."""

    queries_issued: list[str] = Field(default_factory=list)
    providers_used: list[str] = Field(default_factory=list)
    providers_unavailable: list[dict[str, str]] = Field(default_factory=list)
    sources_considered: int = 0
    sources_selected: list[str] = Field(default_factory=list)
    sources_rejected: list[dict[str, str]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    steps: list[ReasoningStep] = Field(default_factory=list)
    computations: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    def step(self, stage: str, detail: str, **data: Any) -> None:
        self.steps.append(ReasoningStep(stage=stage, detail=detail, data=data))


class Answer(BaseModel):
    """What the API returns for any research turn.

    Every rendering of this object answers the three questions the product is
    built around: what did you find, where did it come from, how certain are we.
    """

    id: str = Field(default_factory=lambda: new_id("ans"))
    question: str
    mode: str
    summary: str = ""
    claims: list[Claim] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    disagreements: list[Disagreement] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    trace: Trace = Field(default_factory=Trace)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)

    @property
    def confidence_breakdown(self) -> dict[str, int]:
        out = {e.value: 0 for e in Epistemic}
        for c in self.claims:
            out[c.status.value] += 1
        return out

    def source_by_id(self, sid: str) -> Source | None:
        return next((s for s in self.sources if s.id == sid), None)
