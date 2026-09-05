"""OpenAlex — open catalogue of ~250M scholarly works. No API key needed.

Gives us peer-review status, open-access status, citation counts, retraction
flags and concept tags: exactly the metadata the source-quality rubric needs.
"""
from __future__ import annotations

from datetime import date, datetime

from ...config import settings
from ...core.provenance import Author, Evidentiary, Source, SourceKind
from ...core.registry import ProviderStatus
from ...core.text import normalise
from .base import AcademicProvider, ScholarRequest

BASE = "https://api.openalex.org/works"

_TYPE_MAP = {
    "article": SourceKind.JOURNAL_ARTICLE,
    "journal-article": SourceKind.JOURNAL_ARTICLE,
    "preprint": SourceKind.PREPRINT,
    "book": SourceKind.BOOK,
    "book-chapter": SourceKind.BOOK,
    "dataset": SourceKind.DATASET,
    "report": SourceKind.INSTITUTIONAL,
    "dissertation": SourceKind.INSTITUTIONAL,
}


def _invert_abstract(index: dict[str, list[int]] | None) -> str | None:
    """OpenAlex ships abstracts as an inverted index; rebuild the prose."""
    if not index:
        return None
    positions: list[tuple[int, str]] = []
    for word, spots in index.items():
        positions.extend((spot, word) for spot in spots)
    positions.sort()
    return normalise(" ".join(word for _, word in positions)) or None


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


class OpenAlexProvider(AcademicProvider):
    name = "openalex"
    priority = 10

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            True,
            details={
                "coverage": "cross-disciplinary scholarly works",
                "polite_pool": bool(settings.contact_email),
            },
        )

    def _params(self, request: ScholarRequest) -> dict:
        filters = []
        if request.year_from and request.year_to:
            filters.append(f"publication_year:{request.year_from}-{request.year_to}")
        elif request.year_from:
            filters.append(f"publication_year:>{request.year_from - 1}")
        elif request.year_to:
            filters.append(f"publication_year:<{request.year_to + 1}")
        if request.open_access_only:
            filters.append("is_oa:true")
        if not request.include_preprints:
            filters.append("type:article")
        params = {
            "search": request.query,
            "per-page": min(request.limit, 50),
            "mailto": settings.contact_email,
        }
        if filters:
            params["filter"] = ",".join(filters)
        return params

    def _to_source(self, work: dict) -> Source:
        primary = work.get("primary_location") or {}
        venue = primary.get("source") or {}
        venue_type = (venue.get("type") or "").lower()
        work_type = (work.get("type") or "").lower()
        kind = _TYPE_MAP.get(work_type, SourceKind.JOURNAL_ARTICLE)
        if venue_type == "repository" and work_type in ("article", "preprint"):
            kind = SourceKind.PREPRINT

        authors = []
        for entry in work.get("authorships", [])[:40]:
            person = entry.get("author") or {}
            name = person.get("display_name")
            if not name:
                continue
            insts = entry.get("institutions") or []
            authors.append(
                Author(
                    **Author.parse(name).model_dump(exclude={"orcid", "affiliation"}),
                    orcid=person.get("orcid"),
                    affiliation=(insts[0].get("display_name") if insts else None),
                )
            )

        doi = (work.get("doi") or "").replace("https://doi.org/", "") or None
        ids = work.get("ids") or {}
        pmid = (ids.get("pmid") or "").rsplit("/", 1)[-1] or None
        biblio = work.get("biblio") or {}
        pages = None
        if biblio.get("first_page"):
            pages = biblio["first_page"] + (f"-{biblio['last_page']}" if biblio.get("last_page") else "")

        is_preprint = kind == SourceKind.PREPRINT
        src = Source(
            kind=kind,
            title=normalise(work.get("display_name") or work.get("title") or "Untitled work"),
            url=primary.get("landing_page_url") or work.get("doi") or ids.get("openalex"),
            doi=doi,
            pmid=pmid,
            authors=authors,
            container_title=venue.get("display_name"),
            publisher=venue.get("host_organization_name"),
            published=_parse_date(work.get("publication_date")),
            volume=biblio.get("volume"),
            issue=biblio.get("issue"),
            pages=pages,
            language=work.get("language"),
            license=primary.get("license"),
            abstract=_invert_abstract(work.get("abstract_inverted_index")),
            is_open_access=(work.get("open_access") or {}).get("is_oa"),
            is_peer_reviewed=(not is_preprint) if venue.get("display_name") else None,
            retracted=work.get("is_retracted"),
            cited_by_count=work.get("cited_by_count"),
            evidentiary=Evidentiary.SECONDARY
            if "review" in (work.get("type_crossref") or "")
            else Evidentiary.PRIMARY,
            retrieved_by=self.name,
            full_text_retrieved=False,
            retrieval_note="Metadata + abstract from OpenAlex; full text not fetched.",
            extra={
                "openalex_id": ids.get("openalex"),
                "concepts": [c.get("display_name") for c in (work.get("concepts") or [])[:8]],
                "oa_url": (work.get("best_oa_location") or {}).get("pdf_url"),
                "referenced_works_count": len(work.get("referenced_works") or []),
            },
        )
        src.site_name = src.container_title or src.domain
        return src

    async def search(self, request: ScholarRequest) -> list[Source]:
        data = await self.request_json("GET", BASE, params=self._params(request))
        works = (data or {}).get("results", []) if isinstance(data, dict) else []
        return [self._to_source(w) for w in works]

    async def lookup_doi(self, doi: str) -> Source | None:
        doi = doi.strip().replace("https://doi.org/", "")
        data = await self.request_json(
            "GET", f"{BASE}/doi:{doi}", params={"mailto": settings.contact_email}
        )
        return self._to_source(data) if isinstance(data, dict) and data.get("id") else None
