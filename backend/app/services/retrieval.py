"""Retrieval: turn a question into a ranked, de-duplicated, appraised source set.

The orchestrator asks for evidence; this module decides *where* to look, merges
what comes back, and is scrupulous about recording what it could not do.  A
provider that is missing or fails is written into the trace, never hidden — a
research tool that quietly searches half of what you asked for is worse than one
that says it could not search at all.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ..config import settings
from ..core.errors import ProviderFailed, ProviderUnavailable, WorkspaceError
from ..core.provenance import Source, Trace
from ..core.registry import registry
from ..core.text import best_snippet, overlap_score
from ..providers.academic.base import ScholarRequest
from ..providers.search.base import SearchRequest
from .source_quality import rank


@dataclass(slots=True)
class ResearchControls:
    """User-facing research parameters (spec §20)."""

    max_sources: int = 12
    date_from: date | None = None
    date_to: date | None = None
    source_types: list[str] = field(default_factory=list)     # journal_article, news, ...
    academic_only: bool = False
    web_only: bool = False
    open_access_only: bool = False
    include_preprints: bool = True
    language: str | None = None
    region: str | None = None
    domains_include: list[str] = field(default_factory=list)
    domains_exclude: list[str] = field(default_factory=list)

    def clamp(self) -> "ResearchControls":
        self.max_sources = max(1, min(self.max_sources, settings.max_max_sources))
        return self


async def _gather(tasks: list[tuple[str, Any]], trace: Trace) -> list[Source]:
    """Run provider calls concurrently; record failures rather than raising."""
    if not tasks:
        return []
    results = await asyncio.gather(*(coro for _, coro in tasks), return_exceptions=True)
    out: list[Source] = []
    for (name, _), result in zip(tasks, results):
        if isinstance(result, BaseException):
            reason = (
                result.message if isinstance(result, WorkspaceError) else str(result) or
                type(result).__name__
            )
            trace.providers_unavailable.append({"provider": name, "reason": reason})
            trace.step("search_failed", f"{name} could not be reached: {reason}")
            continue
        trace.providers_used.append(name)
        trace.step("search", f"{name} returned {len(result)} result(s).", provider=name,
                   count=len(result))
        out.extend(result)
    return out


def deduplicate(sources: list[Source]) -> list[Source]:
    """Merge the same work arriving from several providers into one record."""
    merged: dict[str, Source] = {}
    for source in sources:
        key = source.identity_key()
        existing = merged.get(key)
        if existing is None:
            merged[key] = source
            continue
        # Keep the richer record, and remember every provider that found it.
        keep, drop = (existing, source)
        if (len(source.passages), bool(source.abstract), bool(source.doi)) > (
            len(existing.passages), bool(existing.abstract), bool(existing.doi)
        ):
            keep, drop = source, existing
        for field_name in ("doi", "pmid", "arxiv_id", "abstract", "published", "container_title",
                           "publisher", "cited_by_count", "is_open_access", "is_peer_reviewed",
                           "volume", "issue", "pages", "license"):
            if getattr(keep, field_name, None) in (None, "", []) :
                setattr(keep, field_name, getattr(drop, field_name, None))
        if not keep.authors:
            keep.authors = drop.authors
        seen = {p.fingerprint() for p in keep.passages}
        for passage in drop.passages:
            if passage.fingerprint() not in seen:
                passage.source_id = keep.id
                keep.passages.append(passage)
        found_by = set(keep.extra.get("also_found_by") or [])
        found_by.add(drop.retrieved_by)
        keep.extra["also_found_by"] = sorted(found_by - {keep.retrieved_by})
        merged[key] = keep
    return list(merged.values())


def _matches_filters(source: Source, controls: ResearchControls) -> str | None:
    """Return a rejection reason, or None if the source passes."""
    if controls.source_types and source.kind.value not in controls.source_types:
        return f"kind '{source.kind.value}' not in requested types"
    if controls.date_from and source.published and source.published < controls.date_from:
        return f"published {source.published} — before the requested window"
    if controls.date_to and source.published and source.published > controls.date_to:
        return f"published {source.published} — after the requested window"
    if controls.open_access_only and source.is_open_access is False:
        return "not open access"
    if not controls.include_preprints and source.kind.value == "preprint":
        return "preprint excluded by request"
    domain = source.domain or ""
    if controls.domains_include and not any(d in domain for d in controls.domains_include):
        return f"domain '{domain}' not in the allowed list"
    if controls.domains_exclude and any(d in domain for d in controls.domains_exclude):
        return f"domain '{domain}' is excluded"
    return None


def score_relevance(source: Source, question: str) -> float:
    """Cheap lexical relevance over title, abstract and passages."""
    title = overlap_score(question, source.title) * 1.4
    abstract = overlap_score(question, source.abstract or "") * 1.0
    body = max((overlap_score(question, p.text) for p in source.passages[:20]), default=0.0)
    return round(min(title + abstract + body, 3.0), 4)


async def search(
    question: str,
    *,
    controls: ResearchControls,
    trace: Trace,
    use_web: bool = True,
    use_academic: bool = True,
    queries: list[str] | None = None,
) -> list[Source]:
    """Search every configured provider for a question."""
    controls = controls.clamp()
    queries = queries or [question]
    trace.queries_issued.extend(queries)

    tasks: list[tuple[str, Any]] = []
    per_provider = max(4, controls.max_sources)

    if use_academic and not controls.web_only:
        providers = registry.resolve("academic_search", settings.academic_providers)
        if not providers:
            trace.providers_unavailable.append(
                {"provider": "academic_search", "reason": "No academic provider is configured."}
            )
        for provider in providers:
            for query in queries:
                tasks.append(
                    (
                        provider.name,
                        provider.search(
                            ScholarRequest(
                                query=query,
                                limit=per_provider,
                                year_from=controls.date_from.year if controls.date_from else None,
                                year_to=controls.date_to.year if controls.date_to else None,
                                open_access_only=controls.open_access_only,
                                include_preprints=controls.include_preprints,
                            )
                        ),
                    )
                )

    if use_web and not controls.academic_only:
        providers = registry.resolve("web_search", settings.web_search_providers)
        if not providers:
            trace.providers_unavailable.append(
                {
                    "provider": "web_search",
                    "reason": "No web-search provider is configured. Set TAVILY_API_KEY, "
                              "BRAVE_API_KEY, SERPER_API_KEY or SEARXNG_BASE_URL to search "
                              "the open web.",
                }
            )
        for provider in providers:
            for query in queries:
                tasks.append(
                    (
                        provider.name,
                        provider.search(
                            SearchRequest(
                                query=query,
                                limit=per_provider,
                                date_from=controls.date_from,
                                date_to=controls.date_to,
                                language=controls.language,
                                region=controls.region,
                                include_domains=controls.domains_include,
                                exclude_domains=controls.domains_exclude,
                            )
                        ),
                    )
                )

    raw = await _gather(tasks, trace)
    trace.sources_considered += len(raw)
    if not raw:
        trace.step("search", "No provider returned any result for this question.")
        return []

    unique = deduplicate(raw)
    trace.step("deduplicate", f"{len(raw)} result(s) collapsed to {len(unique)} distinct source(s).")

    kept: list[Source] = []
    for source in unique:
        reason = _matches_filters(source, controls)
        if reason:
            trace.sources_rejected.append({"title": source.title[:120], "reason": reason})
            continue
        source.extra["relevance"] = score_relevance(source, question)
        kept.append(source)

    # Rank by evidence quality first, then by lexical relevance within a tier.
    ranked = rank(kept)
    ranked.sort(
        key=lambda s: (
            {"primary_peer_reviewed": 0, "peer_reviewed": 1, "official": 2, "preprint": 3,
             "established_outlet": 4, "user_supplied": 5, "general_web": 6, "unknown": 7}
            .get(s.quality.tier if s.quality else "unknown", 9),
            -(s.extra.get("relevance") or 0),
        )
    )
    selected = ranked[: controls.max_sources]
    trace.sources_selected.extend(s.id for s in selected)
    trace.step(
        "select",
        f"Kept the top {len(selected)} of {len(ranked)} source(s) after quality and "
        f"relevance ranking.",
        tiers={s.quality.tier: 1 for s in selected if s.quality},
    )
    return selected


async def deepen(sources: list[Source], question: str, *, limit: int, trace: Trace) -> list[Source]:
    """Fetch full text for the most promising sources that we only have metadata for.

    Without this step, most answers would rest on abstracts.  With it, the
    grounding layer has real passages to check quotes against.
    """
    candidates = [
        s for s in sources
        if not s.full_text_retrieved and (s.url or s.extra.get("oa_url") or s.extra.get("oa_pdf"))
    ][:limit]
    if not candidates:
        return sources

    epmc = next(
        (p for p in registry.resolve("academic_search", "europepmc")), None
    )
    extractor = None
    try:
        extractor = registry.require("url_extract", settings.extractor_provider)
    except ProviderUnavailable:
        trace.providers_unavailable.append(
            {"provider": "url_extract", "reason": "No URL extractor is configured."}
        )

    async def fetch(source: Source) -> None:
        # Open-access full text from Europe PMC is cleaner than scraping HTML.
        if epmc is not None and source.extra.get("has_full_text"):
            try:
                enriched = await epmc.fetch_full_text(source)
                if enriched.full_text_retrieved:
                    source.passages = enriched.passages
                    source.full_text_retrieved = True
                    source.retrieval_note = enriched.retrieval_note
                    return
            except Exception:
                pass
        if extractor is None:
            return
        url = source.extra.get("oa_url") or source.extra.get("oa_pdf") or source.url
        if not url:
            return
        try:
            fetched = await extractor.extract(url)
        except WorkspaceError as exc:
            source.retrieval_note = (
                f"{source.retrieval_note or ''} Full text not retrieved: {exc.message}"
            ).strip()
            trace.step("fetch_failed", f"Could not read {url}: {exc.message}")
            return
        except Exception as exc:  # noqa: BLE001
            trace.step("fetch_failed", f"Could not read {url}: {exc}")
            return
        if fetched.passages:
            for passage in fetched.passages:
                passage.source_id = source.id
            source.passages = fetched.passages
            source.full_text_retrieved = True
            source.retrieval_note = "Full text fetched from the publisher page."
            source.extra.setdefault("tables", fetched.extra.get("tables"))
            source.extra.setdefault("linked_references", fetched.extra.get("linked_references"))

    await asyncio.gather(*(fetch(s) for s in candidates), return_exceptions=True)

    got = sum(1 for s in candidates if s.full_text_retrieved)
    trace.step(
        "deepen",
        f"Fetched full text for {got} of {len(candidates)} attempted source(s); the rest "
        f"remain abstract-only.",
    )
    # Re-appraise: "full text retrieved" is one of the quality signals.
    for source in candidates:
        source.quality = None
    rank(sources)
    return sources


def focus_passages(sources: list[Source], question: str, *, per_source: int) -> list[Source]:
    """Keep the passages most relevant to the question, so the prompt is evidence-dense."""
    for source in sources:
        if len(source.passages) <= per_source:
            continue
        scored = sorted(
            source.passages,
            key=lambda p: overlap_score(question, p.text),
            reverse=True,
        )
        kept = scored[:per_source]
        # Preserve document order so the model reads them coherently.
        order = {id(p): i for i, p in enumerate(source.passages)}
        source.passages = sorted(kept, key=lambda p: order[id(p)])
    return sources


def snippet_for(source: Source, question: str) -> str:
    text = " ".join(p.text for p in source.passages[:6]) or source.abstract or ""
    return best_snippet(text, question) if text else ""
