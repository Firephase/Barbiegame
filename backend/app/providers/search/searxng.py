"""SearXNG — self-hostable meta-search. No vendor key, just a base URL."""
from __future__ import annotations

from ...config import settings
from ...core.provenance import Source, SourceKind
from ...core.registry import ProviderStatus
from ...core.text import normalise
from .base import SearchRequest, WebSearchProvider


class SearxngSearch(WebSearchProvider):
    name = "searxng"
    priority = 40
    requires_credentials = False

    def status(self) -> ProviderStatus:
        if not settings.searxng_base_url:
            return ProviderStatus(False, "SEARXNG_BASE_URL is not set.")
        return ProviderStatus(True, details={"endpoint": settings.searxng_base_url})

    async def search(self, request: SearchRequest) -> list[Source]:
        params: dict = {"q": request.query, "format": "json", "safesearch": 0}
        if request.language:
            params["language"] = request.language
        data = await self.request_json(
            "GET", settings.searxng_base_url.rstrip("/") + "/search", params=params
        )
        results = (data or {}).get("results", [])[: request.limit] if isinstance(data, dict) else []
        out: list[Source] = []
        for item in results:
            src = Source(
                kind=SourceKind.WEB_PAGE,
                title=normalise(item.get("title") or "") or "Untitled",
                url=item.get("url"),
                abstract=normalise(item.get("content") or "") or None,
                retrieved_by=self.name,
                full_text_retrieved=False,
                retrieval_note="Meta-search snippet only; fetch the URL for full text.",
                extra={"engines": item.get("engines")},
            )
            src.site_name = src.domain
            out.append(src)
        return out
