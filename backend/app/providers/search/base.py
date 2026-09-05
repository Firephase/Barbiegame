"""Web-search capability contract."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ...core.provenance import Source
from ..base import HttpProvider

CAPABILITY = "web_search"


@dataclass(slots=True)
class SearchRequest:
    """User-controlled research parameters (spec §20)."""

    query: str
    limit: int = 10
    date_from: date | None = None
    date_to: date | None = None
    language: str | None = None
    region: str | None = None
    include_domains: list[str] = field(default_factory=list)
    exclude_domains: list[str] = field(default_factory=list)
    #: Ask the provider for page text alongside the hit, when it offers it.
    want_content: bool = True


class WebSearchProvider(HttpProvider):
    capability = CAPABILITY

    async def search(self, request: SearchRequest) -> list[Source]:  # pragma: no cover
        raise NotImplementedError
