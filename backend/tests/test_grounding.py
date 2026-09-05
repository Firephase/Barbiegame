"""The anti-hallucination guarantees (spec §19).

These are the tests that matter most: if any of them regress, the product's
central promise is broken.
"""
from __future__ import annotations

import pytest

from app.core.provenance import Epistemic, Trace
from app.providers.search.fixture import make_source
from app.services.grounding import RetrievalSet, strip_fabricated_dois, verify_answer, verify_claim


@pytest.fixture()
def retrieval():
    s1 = make_source(
        "Study A", "https://a.org",
        "CRISPR base editing reduced tumour volume by 42% in mouse xenografts.",
        doi="10.1000/aaa",
    )
    s2 = make_source(
        "Study B", "https://b.org",
        "Off-target edits were detected at three loci in treated animals.",
    )
    return RetrievalSet.build([s1, s2])


def test_citation_to_unretrieved_source_is_stripped(retrieval):
    """Rule 1: a model cannot cite something that was never retrieved."""
    claim = verify_claim(
        {"text": "Off-target edits occurred.", "status": "verified", "sources": ["S7"]},
        retrieval,
    )
    assert claim.citations == []
    assert claim.status is Epistemic.AI_INFERENCE
    assert "S7" in (claim.verification_note or "")


def test_quote_not_present_in_source_is_removed(retrieval):
    """Rule 2: a quote must actually appear in the cited source."""
    claim = verify_claim(
        {
            "text": "CRISPR base editing reduced tumour volume by 42% in mouse xenografts.",
            "status": "verified",
            "sources": [{"source": "S1", "quote": "reduced tumour volume by 99%"}],
        },
        retrieval,
    )
    assert claim.citations, "a real supporting passage should still be found"
    assert "99%" not in (claim.citations[0].quote or "")


def test_unsupported_claim_loses_its_citation(retrieval):
    """Rule 3: citing a source that does not discuss the claim does not count."""
    claim = verify_claim(
        {
            "text": "This treatment is ready for human clinical use today.",
            "status": "verified",
            "sources": ["S1"],
        },
        retrieval,
    )
    assert claim.status is Epistemic.AI_INFERENCE
    assert claim.citations == []


def test_verified_is_demoted_when_wording_diverges(retrieval):
    """Rule 3 (soft case): weak overlap becomes 'interpretation', not 'verified'."""
    claim = verify_claim(
        {
            "text": "Tumour volume fell substantially in the treated mouse group.",
            "status": "verified",
            "sources": ["S1"],
        },
        retrieval,
    )
    assert claim.status is Epistemic.INTERPRETATION
    assert claim.citations


def test_genuinely_supported_claim_stays_verified(retrieval):
    claim = verify_claim(
        {
            "text": "CRISPR base editing reduced tumour volume by 42% in mouse xenografts.",
            "status": "verified",
            "sources": ["S1"],
        },
        retrieval,
    )
    assert claim.status is Epistemic.VERIFIED
    assert claim.support_score and claim.support_score > 0.9


def test_fabricated_doi_is_removed(retrieval):
    """Rule 5: a DOI no retrieved source carries is deleted, not shown."""
    text, removed = strip_fabricated_dois(
        "See 10.1000/aaa and also 10.9999/invented.", retrieval
    )
    assert removed == ["10.9999/invented."] or removed == ["10.9999/invented"]
    assert "10.1000/aaa" in text
    assert "10.9999/invented" not in text


def test_answer_warns_when_nothing_is_corroborated(retrieval):
    answer = verify_answer(
        {
            "summary": "Findings.",
            "claims": [
                {
                    "text": "CRISPR base editing reduced tumour volume by 42% in mouse xenografts.",
                    "status": "verified",
                    "sources": ["S1"],
                }
            ],
        },
        retrieval,
        question="q",
        mode="quick",
        trace=Trace(),
    )
    assert any("single source" in w for w in answer.warnings)


def test_answer_with_no_grounded_claims_says_so(retrieval):
    answer = verify_answer(
        {
            "summary": "",
            "claims": [{"text": "Something unrelated entirely.", "status": "verified", "sources": []}],
        },
        retrieval,
        question="q",
        mode="quick",
        trace=Trace(),
    )
    assert any("model inference" in w for w in answer.warnings)
    assert answer.confidence_breakdown["ai_inference"] == 1


def test_empty_retrieval_set_is_reported(retrieval):
    answer = verify_answer(
        {"summary": "x", "claims": []},
        RetrievalSet.build([]),
        question="q",
        mode="quick",
        trace=Trace(),
    )
    assert any("No sources were retrieved" in w for w in answer.warnings)


def test_disagreement_marks_a_claim_contested():
    s1 = make_source("A", "https://a.org", "The drug reduced mortality significantly.")
    s2 = make_source("B", "https://b.org", "The drug did not reduce mortality in our cohort.")
    retrieval = RetrievalSet.build([s1, s2])
    answer = verify_answer(
        {
            "summary": "Mixed.",
            "claims": [
                {
                    "text": "The drug reduced mortality significantly.",
                    "status": "verified",
                    "sources": ["S1"],
                }
            ],
            "disagreements": [
                {
                    "topic": "drug mortality reduction",
                    "positions": [
                        {"stance": "Reduces mortality", "sources": ["S1"]},
                        {"stance": "No effect on mortality", "sources": ["S2"]},
                    ],
                }
            ],
        },
        retrieval,
        question="Does the drug reduce mortality?",
        mode="deep_research",
        trace=Trace(),
    )
    claim = answer.claims[0]
    assert claim.contested_by == [s2.id]
    assert claim.status is Epistemic.UNCERTAIN
