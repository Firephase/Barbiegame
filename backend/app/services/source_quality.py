"""Source appraisal.

Spec §18 is explicit: do not reduce credibility to one number.  So this module
produces a *tier* plus a list of named, explained signals.  The UI shows the
explanations; the tier only ever orders a list.

Every judgement here is derived from metadata we actually retrieved.  Where we
do not know something (no author list, no date), the signal says "unknown"
rather than guessing low or high.
"""
from __future__ import annotations

from datetime import date

from ..core.provenance import (
    Evidentiary,
    QualitySignal,
    Source,
    SourceKind,
    SourceQuality,
)

# Domains whose *institutional* status is a matter of public record.  This is a
# statement about who publishes, not about whether a given page is correct.
_GOV_SUFFIXES = (".gov", ".mil", ".gov.uk", ".gc.ca", ".gov.au", ".govt.nz", ".europa.eu")
_IGO_DOMAINS = ("who.int", "un.org", "oecd.org", "worldbank.org", "imf.org", "ecdc.europa.eu",
                "efsa.europa.eu", "ema.europa.eu", "nih.gov", "cdc.gov", "fda.gov", "nice.org.uk")
_ACADEMIC_SUFFIXES = (".edu", ".ac.uk", ".edu.au", ".ac.jp", ".ac.in", ".edu.sg", ".ac.nz")
_PREPRINT_HOSTS = ("arxiv.org", "biorxiv.org", "medrxiv.org", "chemrxiv.org",
                   "ssrn.com", "researchsquare.com", "preprints.org", "osf.io")
_AGGREGATOR_HOSTS = ("wikipedia.org", "quora.com", "reddit.com", "medium.com",
                     "substack.com", "blogspot.com", "wordpress.com", "answers.com")
# Sites whose business model creates a standing interest in the claim.
_COMMERCIAL_HINTS = ("shop", "store", "buy", "pricing", "supplement", "clinic")


def _domain_is(domain: str | None, suffixes: tuple[str, ...]) -> bool:
    if not domain:
        return False
    return any(domain == s.lstrip(".") or domain.endswith(s) for s in suffixes)


def _domain_in(domain: str | None, hosts: tuple[str, ...]) -> bool:
    return bool(domain) and any(domain == h or domain.endswith("." + h) for h in hosts)


def appraise(source: Source, *, today: date | None = None) -> SourceQuality:
    """Return an explained appraisal. Pure function — easy to test, easy to audit."""
    today = today or date.today()
    signals: list[QualitySignal] = []
    caveats: list[str] = []
    domain = source.domain

    # -- 1. publication venue & review status --------------------------
    if source.retracted:
        signals.append(
            QualitySignal(
                dimension="Retraction status",
                verdict="caution",
                explanation="This work is flagged as retracted or corrected. Do not rely on "
                            "its findings without reading the retraction notice.",
                weight=3.0,
            )
        )
        caveats.append("Flagged as retracted or subject to a correction notice.")
    if source.is_peer_reviewed is True:
        signals.append(
            QualitySignal(
                dimension="Peer review",
                verdict="strong",
                explanation=f"Published in {source.container_title or 'a peer-reviewed venue'}, "
                            "so it passed external review before publication.",
                weight=2.0,
            )
        )
    elif source.kind == SourceKind.PREPRINT or _domain_in(domain, _PREPRINT_HOSTS):
        signals.append(
            QualitySignal(
                dimension="Peer review",
                verdict="weak",
                explanation="Preprint — posted without peer review. Findings may change or "
                            "fail to replicate; check whether a journal version exists.",
                weight=2.0,
            )
        )
        caveats.append("Not peer reviewed.")
    elif source.is_peer_reviewed is False:
        signals.append(
            QualitySignal(
                dimension="Peer review",
                verdict="weak",
                explanation="Not peer reviewed.",
                weight=1.5,
            )
        )
    else:
        signals.append(
            QualitySignal(
                dimension="Peer review",
                verdict="unknown",
                explanation="Review status could not be determined from the metadata retrieved.",
                weight=0.5,
            )
        )

    # -- 2. evidence type ----------------------------------------------
    if source.evidentiary == Evidentiary.PRIMARY:
        signals.append(
            QualitySignal(
                dimension="Evidence type",
                verdict="strong",
                explanation="Primary source — reports original data or observations rather "
                            "than restating another study.",
                weight=2.0,
            )
        )
    elif source.evidentiary == Evidentiary.SECONDARY:
        signals.append(
            QualitySignal(
                dimension="Evidence type",
                verdict="adequate",
                explanation="Secondary source — reviews or summarises primary work. Useful for "
                            "orientation; cite the underlying studies for specific claims.",
            )
        )
    elif source.evidentiary == Evidentiary.TERTIARY:
        signals.append(
            QualitySignal(
                dimension="Evidence type",
                verdict="weak",
                explanation="Tertiary source (encyclopaedia or textbook-style summary). Treat "
                            "as a route to primary literature, not as evidence itself.",
                weight=1.5,
            )
        )
        caveats.append("Tertiary source — find the primary study it draws on.")

    # -- 3. institutional standing --------------------------------------
    if _domain_is(domain, _GOV_SUFFIXES) or _domain_in(domain, _IGO_DOMAINS):
        signals.append(
            QualitySignal(
                dimension="Publisher",
                verdict="strong",
                explanation=f"Published by a government or intergovernmental body ({domain}), "
                            "which carries public accountability for what it states.",
                weight=1.5,
            )
        )
    elif _domain_is(domain, _ACADEMIC_SUFFIXES):
        signals.append(
            QualitySignal(
                dimension="Publisher",
                verdict="adequate",
                explanation=f"Hosted by an academic institution ({domain}). Note that personal "
                            "or course pages on university domains are not institutionally vetted.",
            )
        )
    elif _domain_in(domain, _AGGREGATOR_HOSTS):
        signals.append(
            QualitySignal(
                dimension="Publisher",
                verdict="weak",
                explanation=f"User-generated or self-published platform ({domain}) with no "
                            "editorial guarantee.",
                weight=1.5,
            )
        )
    elif source.publisher or source.container_title:
        signals.append(
            QualitySignal(
                dimension="Publisher",
                verdict="adequate",
                explanation=f"Published by {source.publisher or source.container_title}.",
            )
        )
    else:
        signals.append(
            QualitySignal(
                dimension="Publisher",
                verdict="unknown",
                explanation="No publisher or venue could be identified for this page.",
                weight=0.5,
            )
        )

    # -- 4. authorship ---------------------------------------------------
    if source.authors:
        named = source.authors[0].name
        with_orcid = sum(1 for a in source.authors if a.orcid)
        with_affil = sum(1 for a in source.authors if a.affiliation)
        detail = f"Attributed to {named}" + (
            f" and {len(source.authors) - 1} co-author(s)" if len(source.authors) > 1 else ""
        )
        if with_orcid or with_affil:
            detail += f"; {with_affil} with a stated affiliation, {with_orcid} with an ORCID iD"
            verdict = "strong"
        else:
            detail += ". Credentials and affiliations were not available in the metadata"
            verdict = "adequate"
        signals.append(
            QualitySignal(dimension="Authorship", verdict=verdict, explanation=detail + ".")
        )
    else:
        signals.append(
            QualitySignal(
                dimension="Authorship",
                verdict="weak",
                explanation="No named author. Anonymous material cannot be checked against an "
                            "author's record or expertise.",
            )
        )
        caveats.append("No named author.")

    # -- 5. recency -------------------------------------------------------
    if source.published:
        age = (today - source.published).days / 365.25
        if age < 0:
            verdict, note = "unknown", "Publication date is in the future; the metadata may be wrong."
        elif age <= 3:
            verdict, note = "strong", f"Published {source.published:%B %Y} — current."
        elif age <= 8:
            verdict, note = "adequate", (
                f"Published {source.published:%B %Y} ({age:.0f} years ago). Check whether newer "
                "work supersedes it."
            )
        else:
            verdict, note = "weak", (
                f"Published {source.published:%B %Y} ({age:.0f} years ago). In fast-moving fields "
                "this may be outdated; look for more recent replications."
            )
            caveats.append(f"Over {age:.0f} years old.")
        signals.append(QualitySignal(dimension="Recency", verdict=verdict, explanation=note))
    else:
        signals.append(
            QualitySignal(
                dimension="Recency",
                verdict="unknown",
                explanation="No publication date was found, so currency cannot be judged.",
            )
        )
        caveats.append("Undated.")

    # -- 6. uptake by other researchers ------------------------------------
    if source.cited_by_count is not None:
        n = source.cited_by_count
        if n >= 100:
            verdict, note = "strong", f"Cited {n:,} times — widely engaged with by other researchers."
        elif n >= 10:
            verdict, note = "adequate", f"Cited {n} times."
        elif source.published and (today - source.published).days < 550:
            verdict, note = "unknown", (
                f"Cited {n} time(s), but it is recent — citation counts lag publication by "
                "a year or more, so this says little either way."
            )
        else:
            verdict, note = "weak", (
                f"Cited {n} time(s) despite being older. Low uptake is worth noting, though "
                "citation counts also reflect field size and fashion."
            )
        signals.append(
            QualitySignal(dimension="Scholarly uptake", verdict=verdict, explanation=note, weight=0.8)
        )

    # -- 7. accessibility of the evidence -----------------------------------
    if source.full_text_retrieved:
        signals.append(
            QualitySignal(
                dimension="Evidence access",
                verdict="strong",
                explanation="Full text was retrieved, so quotations can be checked in context.",
            )
        )
    else:
        signals.append(
            QualitySignal(
                dimension="Evidence access",
                verdict="weak",
                explanation=(source.retrieval_note or "Only metadata or a snippet was retrieved.")
                + " Claims drawn from this source rest on limited text.",
            )
        )
        caveats.append("Full text not read — only metadata/abstract was available.")

    # -- 8. possible conflicts of interest ----------------------------------
    haystack = " ".join(filter(None, [domain or "", source.publisher or "", source.url or ""])).lower()
    if any(hint in haystack for hint in _COMMERCIAL_HINTS):
        signals.append(
            QualitySignal(
                dimension="Conflicts of interest",
                verdict="caution",
                explanation="This page sits on a commercial site that sells related products, "
                            "so it has a stake in the conclusion. That does not make it wrong, "
                            "but it should be corroborated independently.",
                weight=1.5,
            )
        )
        caveats.append("Commercial site with a potential stake in the claim.")

    tier = _tier_for(source, domain)
    return SourceQuality(
        tier=tier,
        signals=signals,
        summary=_summarise(tier, signals),
        caveats=caveats,
    )


def _tier_for(source: Source, domain: str | None) -> str:
    if source.kind == SourceKind.PREPRINT or _domain_in(domain, _PREPRINT_HOSTS):
        return "preprint"
    if source.is_peer_reviewed and source.evidentiary == Evidentiary.PRIMARY:
        return "primary_peer_reviewed"
    if source.is_peer_reviewed:
        return "peer_reviewed"
    if _domain_is(domain, _GOV_SUFFIXES) or _domain_in(domain, _IGO_DOMAINS):
        return "official"
    if source.kind in (SourceKind.UPLOADED_DOCUMENT, SourceKind.IMAGE, SourceKind.NOTE):
        return "user_supplied"
    if source.publisher or source.container_title:
        return "established_outlet"
    if source.kind == SourceKind.UNKNOWN and not domain:
        return "unknown"
    return "general_web"


_TIER_PROSE = {
    "primary_peer_reviewed": "Peer-reviewed primary research — the strongest routine evidence.",
    "peer_reviewed": "Peer-reviewed, but not reporting original data.",
    "preprint": "Preprint — no peer review yet.",
    "official": "Official government or intergovernmental publication.",
    "established_outlet": "Published by an identifiable outlet.",
    "general_web": "General web page with limited provenance.",
    "user_supplied": "Supplied by you; the workspace makes no independent judgement of it.",
    "unknown": "Provenance could not be established.",
}


def _summarise(tier: str, signals: list[QualitySignal]) -> str:
    strong = [s.dimension.lower() for s in signals if s.verdict == "strong"]
    weak = [s.dimension.lower() for s in signals if s.verdict in ("weak", "caution")]
    parts = [_TIER_PROSE.get(tier, "")]
    if strong:
        parts.append("Strong on " + ", ".join(strong) + ".")
    if weak:
        parts.append("Weaker on " + ", ".join(weak) + ".")
    return " ".join(p for p in parts if p)


def rank(sources: list[Source], *, today: date | None = None) -> list[Source]:
    """Appraise in place and order best-evidence-first (stable within a tier)."""
    order = {
        "primary_peer_reviewed": 0, "peer_reviewed": 1, "official": 2, "preprint": 3,
        "established_outlet": 4, "user_supplied": 5, "general_web": 6, "unknown": 7,
    }
    for src in sources:
        if src.quality is None:
            src.quality = appraise(src, today=today)
    return sorted(
        sources,
        key=lambda s: (
            order.get(s.quality.tier, 9),
            -(s.quality.strong_count - s.quality.weak_count),
            -(s.year or 0),
        ),
    )
