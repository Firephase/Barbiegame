"""arXiv — preprints. Always labelled as *not* peer reviewed."""
from __future__ import annotations

from datetime import datetime
from xml.etree import ElementTree as ET

from ...core.provenance import Author, Evidentiary, Passage, Source, SourceKind
from ...core.registry import ProviderStatus
from ...core.text import normalise
from .base import AcademicProvider, ScholarRequest

BASE = "https://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


class ArxivProvider(AcademicProvider):
    name = "arxiv"
    priority = 30

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            True,
            details={
                "coverage": "physics, maths, CS, quantitative biology preprints",
                "peer_reviewed": False,
            },
        )

    async def search(self, request: ScholarRequest) -> list[Source]:
        xml = await self.request_text(
            "GET",
            BASE,
            params={
                "search_query": f"all:{request.query}",
                "start": 0,
                "max_results": min(request.limit, 50),
                "sortBy": "relevance",
            },
        )
        if not xml:
            return []
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return []

        out: list[Source] = []
        for entry in root.findall("a:entry", NS):
            def text(path: str) -> str:
                node = entry.find(path, NS)
                return normalise(node.text or "") if node is not None else ""

            published = None
            raw_date = text("a:published")
            if raw_date:
                try:
                    published = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
                except ValueError:
                    published = None
            if request.year_from and published and published.year < request.year_from:
                continue
            if request.year_to and published and published.year > request.year_to:
                continue

            abs_url = text("a:id")
            arxiv_id = abs_url.rsplit("/abs/", 1)[-1] if "/abs/" in abs_url else None
            doi_node = entry.find("arxiv:doi", NS)
            summary = text("a:summary")

            src = Source(
                kind=SourceKind.PREPRINT,
                title=text("a:title"),
                url=abs_url or None,
                arxiv_id=arxiv_id,
                doi=normalise(doi_node.text) if doi_node is not None and doi_node.text else None,
                authors=[
                    Author.parse(normalise(n.text or ""))
                    for n in entry.findall("a:author/a:name", NS)
                    if n.text
                ][:40],
                container_title="arXiv",
                site_name="arXiv",
                publisher="arXiv",
                published=published,
                abstract=summary or None,
                is_open_access=True,
                is_peer_reviewed=False,
                evidentiary=Evidentiary.PRIMARY,
                retrieved_by=self.name,
                full_text_retrieved=False,
                retrieval_note="Preprint — not peer reviewed. Abstract retrieved; PDF not parsed.",
                extra={
                    "categories": [
                        c.attrib.get("term") for c in entry.findall("a:category", NS)
                    ],
                    "pdf_url": next(
                        (
                            l.attrib.get("href")
                            for l in entry.findall("a:link", NS)
                            if l.attrib.get("title") == "pdf"
                        ),
                        None,
                    ),
                },
            )
            if summary:
                src.passages.append(
                    Passage(source_id=src.id, text=summary, section="Abstract",
                            char_start=0, char_end=len(summary))
                )
            out.append(src)
        return out
