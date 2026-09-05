"""Crossref — authoritative DOI registration metadata."""
from __future__ import annotations

from datetime import date

from ...config import settings
from ...core.provenance import Author, Evidentiary, Source, SourceKind
from ...core.registry import ProviderStatus
from ...core.text import normalise
from .base import AcademicProvider, ScholarRequest

BASE = "https://api.crossref.org/works"

_TYPE_MAP = {
    "journal-article": SourceKind.JOURNAL_ARTICLE,
    "posted-content": SourceKind.PREPRINT,
    "book": SourceKind.BOOK,
    "book-chapter": SourceKind.BOOK,
    "proceedings-article": SourceKind.JOURNAL_ARTICLE,
    "dataset": SourceKind.DATASET,
    "report": SourceKind.INSTITUTIONAL,
}


def _date_parts(node: dict | None) -> date | None:
    if not node:
        return None
    parts = (node.get("date-parts") or [[]])[0]
    if not parts:
        return None
    year = parts[0]
    month = parts[1] if len(parts) > 1 else 1
    day = parts[2] if len(parts) > 2 else 1
    try:
        return date(int(year), int(month), int(day))
    except (TypeError, ValueError):
        return None


class CrossrefProvider(AcademicProvider):
    name = "crossref"
    priority = 20

    def status(self) -> ProviderStatus:
        return ProviderStatus(True, details={"coverage": "DOI-registered works"})

    def _to_source(self, item: dict) -> Source:
        title_list = item.get("title") or []
        container = item.get("container-title") or []
        authors = [
            Author(
                name=" ".join(filter(None, [a.get("given"), a.get("family")])) or a.get("name", ""),
                given=a.get("given"),
                family=a.get("family"),
                orcid=a.get("ORCID"),
                affiliation=(a.get("affiliation") or [{}])[0].get("name"),
            )
            for a in (item.get("author") or [])[:40]
            if a.get("family") or a.get("name")
        ]
        kind = _TYPE_MAP.get(item.get("type", ""), SourceKind.JOURNAL_ARTICLE)
        src = Source(
            kind=kind,
            title=normalise(title_list[0] if title_list else "Untitled work"),
            url=item.get("URL"),
            doi=item.get("DOI"),
            authors=authors,
            container_title=normalise(container[0]) if container else None,
            publisher=item.get("publisher"),
            published=_date_parts(item.get("issued")) or _date_parts(item.get("created")),
            volume=item.get("volume"),
            issue=item.get("issue"),
            pages=item.get("page"),
            language=item.get("language"),
            abstract=normalise((item.get("abstract") or "").replace("<jats:p>", " ").replace("</jats:p>", " "))
            or None,
            is_peer_reviewed=kind != SourceKind.PREPRINT,
            cited_by_count=item.get("is-referenced-by-count"),
            retracted=bool(item.get("update-to")),
            evidentiary=Evidentiary.PRIMARY,
            retrieved_by=self.name,
            full_text_retrieved=False,
            retrieval_note="Registration metadata from Crossref; full text not fetched.",
            extra={"reference_count": item.get("reference-count"), "subject": item.get("subject")},
        )
        src.site_name = src.container_title or src.publisher
        return src

    async def search(self, request: ScholarRequest) -> list[Source]:
        params: dict = {
            "query.bibliographic": request.query,
            "rows": min(request.limit, 50),
            "mailto": settings.contact_email,
            "select": ",".join(
                [
                    "DOI", "title", "author", "container-title", "issued", "created", "publisher",
                    "URL", "type", "volume", "issue", "page", "abstract", "language", "subject",
                    "is-referenced-by-count", "reference-count", "update-to",
                ]
            ),
        }
        filters = []
        if request.year_from:
            filters.append(f"from-pub-date:{request.year_from}-01-01")
        if request.year_to:
            filters.append(f"until-pub-date:{request.year_to}-12-31")
        if not request.include_preprints:
            filters.append("type:journal-article")
        if filters:
            params["filter"] = ",".join(filters)
        data = await self.request_json("GET", BASE, params=params)
        items = ((data or {}).get("message") or {}).get("items", []) if isinstance(data, dict) else []
        return [self._to_source(i) for i in items]

    async def lookup_doi(self, doi: str) -> Source | None:
        doi = doi.strip().replace("https://doi.org/", "")
        data = await self.request_json(
            "GET", f"{BASE}/{doi}", params={"mailto": settings.contact_email}
        )
        msg = (data or {}).get("message") if isinstance(data, dict) else None
        return self._to_source(msg) if msg else None
