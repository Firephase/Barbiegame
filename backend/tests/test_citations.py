"""Citation formatting across all six styles (spec §2)."""
from __future__ import annotations

from datetime import date

import pytest

from app.core.provenance import Author, Source, SourceKind
from app.services.citations import STYLES, bibliography, format_all, format_citation, in_text


@pytest.fixture()
def article():
    return Source(
        kind=SourceKind.JOURNAL_ARTICLE,
        title="Base editing rescues a disease phenotype in mice",
        authors=[
            Author.parse("Jennifer A Doudna"),
            Author.parse("Emmanuelle Charpentier"),
            Author.parse("Feng Zhang"),
        ],
        container_title="Nature Biotechnology",
        published=date(2023, 7, 14),
        volume="41", issue="7", pages="921-934",
        doi="10.1038/s41587-023-01234-5",
        is_peer_reviewed=True,
    )


@pytest.fixture()
def undated_page():
    return Source(
        kind=SourceKind.WEB_PAGE,
        title="What is CRISPR?",
        url="https://www.cdc.gov/genomics/crispr.html",
        site_name="CDC",
    )


@pytest.mark.parametrize("style", STYLES)
def test_every_style_renders(article, style):
    text = format_citation(article, style)
    assert text.strip()
    assert "Doudna" in text
    assert "2023" in text


def test_apa_shape(article):
    assert format_citation(article, "apa").startswith("Doudna, J. A., Charpentier, E., & Zhang, F. (2023).")


def test_vancouver_shape(article):
    assert format_citation(article, "vancouver").startswith("Doudna JA, Charpentier E, Zhang F.")


def test_ieee_initials_lead(article):
    assert format_citation(article, "ieee").startswith("J. A. Doudna")


def test_bibtex_is_parseable(article):
    entry = format_citation(article, "bibtex")
    assert entry.startswith("@article{doudna2023base,")
    assert entry.count("{") == entry.count("}")
    assert "doi = {10.1038/s41587-023-01234-5}" in entry


def test_undated_source_says_nd_rather_than_guessing(undated_page):
    """A fabricated year in a reference list is a fabricated citation."""
    assert "n.d." in format_citation(undated_page, "apa")
    assert "[date unknown]" in format_citation(undated_page, "vancouver")


def test_no_style_invents_an_author(undated_page):
    for style in STYLES:
        rendered = format_citation(undated_page, style)
        assert "et al" not in rendered.lower()


def test_in_text_markers(article, undated_page):
    assert in_text(article, "apa") == "(Doudna et al., 2023)"
    assert in_text(article, "mla") == "(Doudna et al.)"
    assert in_text(article, "ieee", index=4) == "[4]"
    assert "n.d." in in_text(undated_page, "apa")


def test_numbered_bibliography(article, undated_page):
    listed = bibliography([article, undated_page], "ieee")
    assert listed.startswith("[1] ")
    assert "\n[2] " in listed


def test_alphabetised_bibliography(article, undated_page):
    """Author-date styles sort by the leading element, whatever order they arrive in."""
    listed = bibliography([article, undated_page], "apa")
    assert listed.index("CDC") < listed.index("Doudna")


def test_preprint_is_flagged_everywhere():
    preprint = Source(
        kind=SourceKind.PREPRINT, title="A preprint", published=date(2025, 1, 1),
        authors=[Author.parse("A Researcher")], container_title="bioRxiv",
    )
    assert "[Preprint]" in format_citation(preprint, "apa")
    assert "Preprint" in format_citation(preprint, "bibtex")


def test_format_all_covers_every_style(article):
    assert set(format_all(article)) == set(STYLES)


def test_unknown_style_raises(article):
    with pytest.raises(ValueError):
        format_citation(article, "harvard")
