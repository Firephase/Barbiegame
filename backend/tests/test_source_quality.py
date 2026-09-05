"""Source appraisal (spec §18): explained, never a single opaque score."""
from __future__ import annotations

from datetime import date, timedelta

from app.core.provenance import Author, Evidentiary, Source, SourceKind
from app.services.source_quality import appraise, rank

TODAY = date(2026, 1, 1)


def _source(**kwargs) -> Source:
    base = dict(title="A study", full_text_retrieved=True)
    return Source(**{**base, **kwargs})


def test_every_appraisal_explains_itself():
    quality = appraise(_source(url="https://example.com/x"), today=TODAY)
    assert quality.signals
    for signal in quality.signals:
        assert signal.explanation.strip(), f"{signal.dimension} has no explanation"
    assert quality.summary


def test_peer_reviewed_primary_research_is_top_tier():
    quality = appraise(
        _source(
            kind=SourceKind.JOURNAL_ARTICLE, is_peer_reviewed=True,
            evidentiary=Evidentiary.PRIMARY, container_title="Nature",
            published=date(2025, 1, 1), authors=[Author.parse("A B")],
        ),
        today=TODAY,
    )
    assert quality.tier == "primary_peer_reviewed"


def test_preprint_is_flagged_as_not_reviewed():
    quality = appraise(
        _source(kind=SourceKind.PREPRINT, url="https://www.biorxiv.org/x"), today=TODAY
    )
    assert quality.tier == "preprint"
    assert any("Not peer reviewed" in c for c in quality.caveats)


def test_government_source_is_recognised():
    quality = appraise(_source(url="https://www.cdc.gov/page"), today=TODAY)
    assert quality.tier == "official"
    assert any(s.dimension == "Publisher" and s.verdict == "strong" for s in quality.signals)


def test_retraction_is_the_loudest_signal():
    quality = appraise(_source(retracted=True, is_peer_reviewed=True), today=TODAY)
    signal = next(s for s in quality.signals if s.dimension == "Retraction status")
    assert signal.verdict == "caution"
    assert signal.weight >= 3.0


def test_old_source_is_caveated():
    quality = appraise(_source(published=TODAY - timedelta(days=365 * 12)), today=TODAY)
    recency = next(s for s in quality.signals if s.dimension == "Recency")
    assert recency.verdict == "weak"


def test_recent_paper_with_few_citations_is_not_penalised():
    """Citation counts lag publication; a new paper's low count says nothing."""
    quality = appraise(
        _source(published=TODAY - timedelta(days=200), cited_by_count=0), today=TODAY
    )
    uptake = next(s for s in quality.signals if s.dimension == "Scholarly uptake")
    assert uptake.verdict == "unknown"


def test_missing_metadata_reads_as_unknown_not_bad():
    quality = appraise(_source(url="https://example.com/x"), today=TODAY)
    recency = next(s for s in quality.signals if s.dimension == "Recency")
    assert recency.verdict == "unknown"


def test_abstract_only_source_is_flagged():
    quality = appraise(_source(full_text_retrieved=False), today=TODAY)
    assert any("Full text not read" in c for c in quality.caveats)


def test_wikipedia_style_tertiary_source_is_demoted():
    quality = appraise(
        _source(url="https://en.wikipedia.org/wiki/CRISPR", evidentiary=Evidentiary.TERTIARY),
        today=TODAY,
    )
    assert any("primary" in c.lower() for c in quality.caveats)


def test_ranking_puts_best_evidence_first():
    peer = _source(
        title="Peer reviewed", kind=SourceKind.JOURNAL_ARTICLE, is_peer_reviewed=True,
        evidentiary=Evidentiary.PRIMARY, published=date(2025, 1, 1),
    )
    blog = _source(title="Blog", url="https://medium.com/@x/post")
    preprint = _source(title="Preprint", kind=SourceKind.PREPRINT)
    ordered = rank([blog, preprint, peer], today=TODAY)
    assert [s.title for s in ordered][0] == "Peer reviewed"
    assert [s.title for s in ordered][-1] == "Blog"
