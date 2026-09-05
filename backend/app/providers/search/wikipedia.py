"""Wikipedia search — no credentials, always available.

Included so ``auto`` mode is never completely blind out of the box.  It is
registered at the lowest priority and its results are explicitly typed as
*tertiary* evidence: an encyclopaedia is a place to find primary sources, not
a substitute for them, and the source-quality rubric says so to the user.
"""
from __future__ import annotations

from urllib.parse import quote

from ...core.provenance import Author, Evidentiary, Passage, Source, SourceKind
from ...core.registry import ProviderStatus
from ...core.text import chunk, normalise
from .base import SearchRequest, WebSearchProvider

API = "https://{lang}.wikipedia.org/w/api.php"


class WikipediaSearch(WebSearchProvider):
    name = "wikipedia"
    priority = 90
    requires_credentials = False

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            True,
            details={
                "returns_page_content": True,
                "evidence_tier": "tertiary — use to locate primary sources, not to cite as one",
            },
        )

    async def search(self, request: SearchRequest) -> list[Source]:
        lang = (request.language or "en").split("-")[0]
        endpoint = API.format(lang=lang)
        found = await self.request_json(
            "GET",
            endpoint,
            params={
                "action": "query",
                "list": "search",
                "srsearch": request.query,
                "srlimit": min(request.limit, 10),
                "format": "json",
                "srprop": "timestamp",
            },
        )
        hits = ((found or {}).get("query") or {}).get("search", []) if isinstance(found, dict) else []
        if not hits:
            return []

        titles = "|".join(h["title"] for h in hits)
        pages_data = await self.request_json(
            "GET",
            endpoint,
            params={
                "action": "query",
                "prop": "extracts|info",
                "titles": titles,
                "explaintext": 1,
                "exsectionformat": "plain",
                "inprop": "url",
                "format": "json",
            },
        )
        pages = ((pages_data or {}).get("query") or {}).get("pages", {}) if isinstance(pages_data, dict) else {}

        out: list[Source] = []
        for page in pages.values():
            if "missing" in page:
                continue
            body = normalise(page.get("extract") or "")
            title = page.get("title", "Untitled")
            src = Source(
                kind=SourceKind.WEB_PAGE,
                title=title,
                url=page.get("fullurl") or f"https://{lang}.wikipedia.org/wiki/{quote(title)}",
                container_title="Wikipedia",
                site_name="Wikipedia",
                publisher="Wikimedia Foundation",
                authors=[Author(name="Wikipedia contributors")],
                language=lang,
                license="CC BY-SA 4.0",
                evidentiary=Evidentiary.TERTIARY,
                is_peer_reviewed=False,
                retrieved_by=self.name,
                full_text_retrieved=bool(body),
                retrieval_note="Encyclopaedia entry — treat as a pointer to primary literature.",
                abstract=body[:1000] or None,
            )
            for start, end, text in chunk(body)[:30]:
                src.passages.append(
                    Passage(source_id=src.id, text=text, char_start=start, char_end=end)
                )
            out.append(src)
        return out
