"""Serper.dev — Google SERP proxy."""
from __future__ import annotations

from ...config import settings
from ...core.provenance import Source, SourceKind
from ...core.registry import ProviderStatus
from ...core.text import normalise
from .base import SearchRequest, WebSearchProvider

ENDPOINT = "https://google.serper.dev/search"


class SerperSearch(WebSearchProvider):
    name = "serper"
    priority = 30

    def status(self) -> ProviderStatus:
        if not settings.serper_api_key:
            return ProviderStatus(False, "SERPER_API_KEY is not set.")
        return ProviderStatus(True, details={"returns_page_content": False})

    async def search(self, request: SearchRequest) -> list[Source]:
        payload: dict = {"q": request.query, "num": min(request.limit, 20)}
        if request.region:
            payload["gl"] = request.region.lower()
        if request.language:
            payload["hl"] = request.language
        data = await self.request_json(
            "POST", ENDPOINT, json=payload,
            headers={"X-API-KEY": settings.serper_api_key, "Content-Type": "application/json"},
        )
        organic = (data or {}).get("organic", []) if isinstance(data, dict) else []
        out: list[Source] = []
        for item in organic:
            src = Source(
                kind=SourceKind.WEB_PAGE,
                title=normalise(item.get("title") or "") or "Untitled",
                url=item.get("link"),
                abstract=normalise(item.get("snippet") or "") or None,
                retrieved_by=self.name,
                full_text_retrieved=False,
                retrieval_note="Search-result snippet only; fetch the URL for full text.",
                extra={"position": item.get("position")},
            )
            src.site_name = src.domain
            out.append(src)
        return out
