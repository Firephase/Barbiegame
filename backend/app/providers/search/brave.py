"""Brave Search API — independent index, returns metadata + descriptions."""
from __future__ import annotations

from datetime import datetime

from ...config import settings
from ...core.provenance import Source, SourceKind
from ...core.registry import ProviderStatus
from ...core.text import normalise
from .base import SearchRequest, WebSearchProvider

ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class BraveSearch(WebSearchProvider):
    name = "brave"
    priority = 20

    def status(self) -> ProviderStatus:
        if not settings.brave_api_key:
            return ProviderStatus(False, "BRAVE_API_KEY is not set.")
        return ProviderStatus(True, details={"returns_page_content": False})

    async def search(self, request: SearchRequest) -> list[Source]:
        params: dict = {"q": request.query, "count": min(request.limit, 20)}
        if request.language:
            params["search_lang"] = request.language
        if request.region:
            params["country"] = request.region
        if request.date_from:
            end = (request.date_to or datetime.utcnow().date()).strftime("%Y-%m-%d")
            params["freshness"] = f"{request.date_from:%Y-%m-%d}to{end}"

        data = await self.request_json(
            "GET",
            ENDPOINT,
            params=params,
            headers={
                "X-Subscription-Token": settings.brave_api_key,
                "Accept": "application/json",
            },
        )
        results = ((data or {}).get("web") or {}).get("results", []) if isinstance(data, dict) else []
        out: list[Source] = []
        for item in results:
            src = Source(
                kind=SourceKind.WEB_PAGE,
                title=normalise(item.get("title") or "") or item.get("url", "Untitled"),
                url=item.get("url"),
                abstract=normalise(item.get("description") or "") or None,
                retrieved_by=self.name,
                full_text_retrieved=False,
                retrieval_note="Search-result snippet only; fetch the URL for full text.",
                extra={"page_age": item.get("page_age")},
            )
            src.site_name = (item.get("profile") or {}).get("name") or src.domain
            out.append(src)
        return out
