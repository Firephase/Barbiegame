"""Europe PMC — biomedical literature, incl. PubMed records and OA full text.

Where a work is open access, we pull the full text so claims about it can be
grounded in real passages rather than an abstract.
"""
from __future__ import annotations

from datetime import datetime

from ...core.provenance import Author, Evidentiary, Passage, Source, SourceKind
from ...core.registry import ProviderStatus
from ...core.text import chunk, normalise
from .base import AcademicProvider, ScholarRequest

SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
FULLTEXT = "https://www.ebi.ac.uk/europepmc/webservices/rest/{src}/{pid}/fullTextXML"


class EuropePMCProvider(AcademicProvider):
    name = "europepmc"
    priority = 15

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            True, details={"coverage": "biomedical + life sciences", "open_access_full_text": True}
        )

    def _to_source(self, item: dict) -> Source:
        published = None
        raw = item.get("firstPublicationDate") or item.get("pubYear")
        if raw and len(str(raw)) >= 10:
            try:
                published = datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
            except ValueError:
                published = None
        elif raw:
            try:
                published = datetime.strptime(f"{int(raw)}-01-01", "%Y-%m-%d").date()
            except (ValueError, TypeError):
                published = None

        pub_type = " ".join(item.get("pubTypeList", {}).get("pubType", [])).lower() \
            if isinstance(item.get("pubTypeList"), dict) else ""
        is_preprint = "preprint" in pub_type or item.get("source") == "PPR"
        is_review = "review" in pub_type

        src = Source(
            kind=SourceKind.PREPRINT if is_preprint else SourceKind.JOURNAL_ARTICLE,
            title=normalise(item.get("title") or "Untitled work"),
            url=f"https://europepmc.org/article/{item.get('source', 'MED')}/{item.get('id')}",
            doi=item.get("doi"),
            pmid=item.get("pmid"),
            authors=[Author.parse(a) for a in (item.get("authorString") or "").split(", ") if a][:40],
            container_title=item.get("journalTitle") or item.get("bookOrReportDetails", {}).get("publisher"),
            published=published,
            is_open_access=item.get("isOpenAccess") == "Y",
            is_peer_reviewed=not is_preprint,
            evidentiary=Evidentiary.SECONDARY if is_review else Evidentiary.PRIMARY,
            cited_by_count=item.get("citedByCount"),
            abstract=normalise(item.get("abstractText") or "") or None,
            retrieved_by=self.name,
            full_text_retrieved=False,
            retrieval_note="Abstract + metadata from Europe PMC.",
            extra={
                "epmc_source": item.get("source"),
                "epmc_id": item.get("id"),
                "has_full_text": item.get("hasTextMinedTerms") == "Y"
                or item.get("inEPMC") == "Y",
                "pub_types": pub_type or None,
            },
        )
        src.site_name = src.container_title or "Europe PMC"
        if src.abstract:
            src.passages.append(
                Passage(source_id=src.id, text=src.abstract, section="Abstract",
                        char_start=0, char_end=len(src.abstract))
            )
        return src

    async def search(self, request: ScholarRequest) -> list[Source]:
        query = request.query
        if request.year_from or request.year_to:
            lo = request.year_from or 1800
            hi = request.year_to or datetime.utcnow().year
            query = f"({query}) AND (FIRST_PDATE:[{lo}-01-01 TO {hi}-12-31])"
        if request.open_access_only:
            query = f"({query}) AND (OPEN_ACCESS:y)"
        if not request.include_preprints:
            query = f"({query}) NOT (SRC:PPR)"

        data = await self.request_json(
            "GET",
            SEARCH,
            params={
                "query": query,
                "format": "json",
                "pageSize": min(request.limit, 50),
                "resultType": "core",
            },
        )
        items = ((data or {}).get("resultList") or {}).get("result", []) if isinstance(data, dict) else []
        return [self._to_source(i) for i in items]

    async def fetch_full_text(self, source: Source) -> Source:
        """Pull OA full text into passages. Returns the source unchanged on failure."""
        epmc_src, pid = source.extra.get("epmc_source"), source.extra.get("epmc_id")
        if not (epmc_src and pid and source.extra.get("has_full_text")):
            return source
        try:
            xml = await self.request_text("GET", FULLTEXT.format(src=epmc_src, pid=pid), retries=0)
        except Exception:
            return source
        if not xml:
            return source

        from xml.etree import ElementTree as ET

        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return source

        body = root.find(".//body")
        if body is None:
            return source
        source.passages = [p for p in source.passages if p.section == "Abstract"]
        for sec in body.iter("sec"):
            title_node = sec.find("title")
            section = normalise(title_node.text or "") if title_node is not None else None
            text = normalise(" ".join(t for t in sec.itertext()))
            if not text or len(text) < 80:
                continue
            for start, end, part in chunk(text):
                source.passages.append(
                    Passage(source_id=source.id, text=part, section=section,
                            char_start=start, char_end=end)
                )
        if len(source.passages) > 1:
            source.full_text_retrieved = True
            source.retrieval_note = "Open-access full text retrieved from Europe PMC."
        return source
