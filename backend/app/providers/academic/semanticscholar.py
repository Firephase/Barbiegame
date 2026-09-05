"""Semantic Scholar — adds influential-citation counts and TL;DRs.

Works without a key at a low rate limit; a key raises it.
"""
from __future__ import annotations

from datetime import datetime

from ...config import settings
from ...core.provenance import Author, Evidentiary, Source, SourceKind
from ...core.registry import ProviderStatus
from ...core.text import normalise
from .base import AcademicProvider, ScholarRequest

BASE = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = (
    "title,abstract,year,publicationDate,authors,externalIds,venue,url,openAccessPdf,"
    "citationCount,influentialCitationCount,publicationTypes,isOpenAccess,tldr"
)


class SemanticScholarProvider(AcademicProvider):
    name = "semanticscholar"
    priority = 40

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            True,
            details={
                "keyed": bool(settings.semanticscholar_api_key),
                "note": "Unauthenticated requests are heavily rate limited.",
            },
        )

    async def search(self, request: ScholarRequest) -> list[Source]:
        params: dict = {"query": request.query, "limit": min(request.limit, 50), "fields": FIELDS}
        if request.year_from or request.year_to:
            lo = request.year_from or ""
            hi = request.year_to or ""
            params["year"] = f"{lo}-{hi}"
        headers = (
            {"x-api-key": settings.semanticscholar_api_key}
            if settings.semanticscholar_api_key
            else {}
        )
        data = await self.request_json("GET", BASE, params=params, headers=headers, retries=1)
        papers = (data or {}).get("data", []) if isinstance(data, dict) else []

        out: list[Source] = []
        for p in papers:
            ext = p.get("externalIds") or {}
            types = [t.lower() for t in (p.get("publicationTypes") or [])]
            is_review = "review" in types
            published = None
            if p.get("publicationDate"):
                try:
                    published = datetime.strptime(p["publicationDate"][:10], "%Y-%m-%d").date()
                except ValueError:
                    published = None
            elif p.get("year"):
                try:
                    published = datetime(int(p["year"]), 1, 1).date()
                except (TypeError, ValueError):
                    published = None
            tldr = (p.get("tldr") or {}).get("text")
            src = Source(
                kind=SourceKind.JOURNAL_ARTICLE,
                title=normalise(p.get("title") or "Untitled work"),
                url=p.get("url"),
                doi=ext.get("DOI"),
                pmid=str(ext["PubMed"]) if ext.get("PubMed") else None,
                arxiv_id=ext.get("ArXiv"),
                authors=[Author.parse(a["name"]) for a in (p.get("authors") or []) if a.get("name")][:40],
                container_title=p.get("venue") or None,
                published=published,
                abstract=normalise(p.get("abstract") or "") or None,
                is_open_access=p.get("isOpenAccess"),
                cited_by_count=p.get("citationCount"),
                evidentiary=Evidentiary.SECONDARY if is_review else Evidentiary.PRIMARY,
                retrieved_by=self.name,
                full_text_retrieved=False,
                retrieval_note="Metadata + abstract from Semantic Scholar.",
                extra={
                    "influential_citations": p.get("influentialCitationCount"),
                    "publication_types": types,
                    # Machine-generated one-liner: labelled so it is never mistaken
                    # for the authors' own words.
                    "machine_tldr": tldr,
                    "oa_pdf": (p.get("openAccessPdf") or {}).get("url"),
                },
            )
            src.site_name = src.container_title
            out.append(src)
        return out
