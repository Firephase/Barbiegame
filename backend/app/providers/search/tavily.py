"""Tavily — search API that returns extracted page content with each hit."""
from __future__ import annotations

from datetime import date, datetime

from ...config import settings
from ...core.provenance import Passage, Source, SourceKind
from ...core.registry import ProviderStatus
from ...core.text import chunk, normalise
from .base import SearchRequest, WebSearchProvider

ENDPOINT = "https://api.tavily.com/search"


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    return None


class TavilySearch(WebSearchProvider):
    name = "tavily"
    priority = 10

    def status(self) -> ProviderStatus:
        if not settings.tavily_api_key:
            return ProviderStatus(False, "TAVILY_API_KEY is not set.")
        return ProviderStatus(True, details={"returns_page_content": True})

    async def search(self, request: SearchRequest) -> list[Source]:
        payload: dict = {
            "api_key": settings.tavily_api_key,
            "query": request.query,
            "max_results": min(request.limit, 20),
            "search_depth": "advanced",
            "include_raw_content": request.want_content,
        }
        if request.include_domains:
            payload["include_domains"] = request.include_domains
        if request.exclude_domains:
            payload["exclude_domains"] = request.exclude_domains
        if request.date_from:
            delta = (date.today() - request.date_from).days
            if delta > 0:
                payload["days"] = delta

        data = await self.request_json("POST", ENDPOINT, json=payload)
        results = (data or {}).get("results", []) if isinstance(data, dict) else []

        sources: list[Source] = []
        for item in results:
            body = normalise(item.get("raw_content") or item.get("content") or "")
            src = Source(
                kind=SourceKind.WEB_PAGE,
                title=item.get("title") or item.get("url") or "Untitled page",
                url=item.get("url"),
                published=_parse_date(item.get("published_date")),
                retrieved_by=self.name,
                full_text_retrieved=bool(item.get("raw_content")),
                abstract=normalise(item.get("content") or "")[:1200] or None,
                extra={"provider_score": item.get("score")},
            )
            src.site_name = src.domain
            for start, end, text in chunk(body)[:24]:
                src.passages.append(
                    Passage(source_id=src.id, text=text, char_start=start, char_end=end)
                )
            sources.append(src)
        return sources
