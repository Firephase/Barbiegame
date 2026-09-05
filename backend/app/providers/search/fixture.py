"""Deterministic in-memory search, for tests and offline demos.

It is *never* auto-selected: ``requires_credentials`` is True and the status
check demands ``FIXTURE_SEARCH=1``, so a developer cannot accidentally ship
synthetic sources into a real research session.
"""
from __future__ import annotations

import os

from ...core.provenance import Passage, Source, new_id
from ...core.registry import ProviderStatus
from ...core.text import content_tokens
from .base import SearchRequest, WebSearchProvider


class FixtureSearch(WebSearchProvider):
    name = "fixture"
    priority = 999

    def __init__(self, corpus: list[Source] | None = None) -> None:
        self.corpus = corpus or []

    def status(self) -> ProviderStatus:
        if os.environ.get("FIXTURE_SEARCH") != "1":
            return ProviderStatus(False, "Set FIXTURE_SEARCH=1 to enable the offline fixture corpus.")
        return ProviderStatus(True, details={"documents": len(self.corpus), "synthetic": True})

    def load(self, sources: list[Source]) -> None:
        self.corpus = sources

    async def search(self, request: SearchRequest) -> list[Source]:
        q = set(content_tokens(request.query))
        scored: list[tuple[int, Source]] = []
        for src in self.corpus:
            haystack = " ".join(
                [src.title, src.abstract or "", *(p.text for p in src.passages)]
            )
            score = len(q & set(content_tokens(haystack)))
            if score:
                scored.append((score, src))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        out = []
        for score, src in scored[: request.limit]:
            copy = src.model_copy(deep=True)
            # Each retrieval yields a fresh Source, exactly as a live provider does.
            copy.id = new_id("src")
            copy.retrieved_by = self.name
            copy.extra["fixture_score"] = score
            for p in copy.passages:
                p.id = new_id("psg")
                p.source_id = copy.id
            out.append(copy)
        return out


def make_source(title: str, url: str, text: str, **kw) -> Source:
    """Helper for tests: build a source whose passages really contain ``text``."""
    src = Source(title=title, url=url, retrieved_by="fixture", full_text_retrieved=True, **kw)
    src.passages = [Passage(source_id=src.id, text=text, char_start=0, char_end=len(text))]
    src.abstract = text[:400]
    return src
