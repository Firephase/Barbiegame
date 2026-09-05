"""The research orchestrator.

One entry point, ``run_research``, drives the whole loop:

    understand → retrieve → deepen → focus → reason → verify → record

Follow-ups (spec §16) re-enter the same loop carrying the project's memory, so
"now only show studies from the last five years" refines the existing research
instead of starting over.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..core.errors import ProviderUnavailable
from ..core.provenance import Answer, Source, Trace
from ..core.registry import registry
from ..providers.llm.base import LlmMessage, LlmRequest
from . import memory as memory_service
from .grounding import RetrievalSet, verify_answer
from .modes import ANSWER_SCHEMA, Mode, build_system_prompt, get_mode
from .retrieval import ResearchControls, deepen, focus_passages, search

DEPTH_NOTES = {
    "brief": "Keep the answer tight: a short summary and the essential claims only.",
    "standard": "",
    "thorough": "Be thorough. Cover the significant lines of evidence, not just the strongest one.",
}

LEVEL_NOTES = {
    "beginner": "Write for someone new to the field. Define terms as they appear.",
    "student": "Write for a student who knows the basics.",
    "researcher": "Write for a working researcher; assume methodological literacy.",
    "expert": "Write for a specialist. Be terse and precise.",
}


@dataclass(slots=True)
class ResearchRequest:
    question: str
    project_id: str | None = None
    mode: str = "quick"
    controls: ResearchControls = field(default_factory=ResearchControls)
    #: Restrict reasoning to these sources (e.g. "compare these three papers").
    source_ids: list[str] = field(default_factory=list)
    #: Search the web even in project-only modes.
    force_search: bool = False
    #: Skip searching entirely and reason over what the project already holds.
    use_project_only: bool = False
    depth: str = "standard"
    level: str = "researcher"
    citation_style: str = "apa"
    language: str | None = None


async def run_research(
    request: ResearchRequest,
    *,
    session: Session | None = None,
) -> Answer:
    started = time.perf_counter()
    mode: Mode = get_mode(request.mode)
    trace = Trace()
    controls = request.controls.clamp()
    if controls.max_sources == ResearchControls().max_sources:
        controls.max_sources = mode.max_sources

    trace.step(
        "plan",
        f"Mode '{mode.label}' with up to {controls.max_sources} sources.",
        mode=mode.name,
        academic=mode.use_academic and not controls.web_only,
        web=mode.use_web and not controls.academic_only,
    )
    _record_assumptions(trace, controls, mode)

    # -- 1. what the project already knows (spec §13) --------------------
    project_sources: list[Source] = []
    project_digest = ""
    if request.project_id and session is not None:
        project_memory = memory_service.load_memory(session, request.project_id)
        project_digest = memory_service.context_digest(project_memory)
        if request.source_ids:
            project_sources = [
                s for s in project_memory.sources if s.id in set(request.source_ids)
            ]
            trace.step("recall", f"Restricted to {len(project_sources)} chosen source(s).")
        else:
            project_sources = memory_service.recall(
                session, request.project_id, request.question,
                limit=max(mode.max_sources, 12),
            )
            trace.step(
                "recall",
                f"Found {len(project_sources)} source(s) in this project matching the question, "
                f"out of {len(project_memory.sources)} collected.",
            )

    # -- 2. search the world --------------------------------------------
    found: list[Source] = []
    should_search = (
        not request.use_project_only
        and ((mode.use_web or mode.use_academic) or request.force_search)
    )
    if should_search:
        found = await search(
            request.question,
            controls=controls,
            trace=trace,
            use_web=mode.use_web or request.force_search,
            use_academic=mode.use_academic or request.force_search,
        )
    elif not project_sources:
        trace.step(
            "search",
            f"'{mode.label}' works from material already in the project, and nothing "
            f"in it matched this question.",
        )

    # -- 3. combine, preferring what the project already holds -----------
    combined: list[Source] = []
    seen_keys: set[str] = set()
    for source in [*project_sources, *found]:
        key = source.identity_key()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        combined.append(source)
    combined = combined[: controls.max_sources]

    if not combined:
        return _empty_answer(request, mode, trace, started)

    # -- 4. read the promising ones properly -----------------------------
    if mode.fetch_full_text and found:
        combined = await deepen(combined, request.question, limit=mode.deep_fetch_limit, trace=trace)
    combined = focus_passages(combined, request.question, per_source=mode.passages_per_source)

    # -- 5. reason --------------------------------------------------------
    retrieval = RetrievalSet.build(combined)
    context = retrieval.render_context(
        per_source=mode.passages_per_source, char_budget=mode.char_budget
    )
    if not context:
        trace.limitations.append(
            "Sources were found but none carried readable text, so no claim could be grounded."
        )

    provider = _pick_llm(mode, trace)
    system = build_system_prompt(
        mode,
        depth_note=DEPTH_NOTES.get(request.depth, ""),
        style_note=LEVEL_NOTES.get(request.level, ""),
    )
    prompt = _build_prompt(request, mode, combined, context, project_digest)

    trace.step(
        "reason",
        f"Sent {len(context)} passage(s) from {len(combined)} source(s) to "
        f"{provider.name}.",
        provider=provider.name,
        characters=sum(len(b["text"]) for b in context),
    )

    result = await provider.complete(
        LlmRequest(
            messages=[LlmMessage(role="user", content=prompt)],
            system=system,
            intent="answer",
            json_schema=ANSWER_SCHEMA,
            max_tokens=mode.max_tokens,
            temperature=mode.temperature,
            tier=mode.tier,
            context_passages=context,
        )
    )
    payload = result.structured
    if payload is None:
        from ..providers.llm.base import parse_json_payload

        payload = parse_json_payload(result.text) or {
            "summary": result.text.strip(),
            "claims": [],
            "limitations": [
                "The model did not return structured output, so nothing in this answer "
                "has been citation-checked. Treat all of it as unverified."
            ],
        }

    # -- 6. verify (the part that makes this trustworthy) ------------------
    answer = verify_answer(
        payload, retrieval, question=request.question, mode=mode.name, trace=trace
    )
    if result.extractive_only:
        answer.warnings.insert(
            0,
            "No reasoning model is configured, so this answer is assembled from verbatim "
            "quotes rather than written. Set ANTHROPIC_API_KEY or OPENAI_API_KEY for "
            "synthesis, comparison and interpretation.",
        )
    trace.step(
        "verify",
        "Checked every citation against the retrieved set: "
        + ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in answer.confidence_breakdown.items()),
        model=result.model,
        usage=result.usage,
    )
    trace.steps[-1].duration_ms = int((time.perf_counter() - started) * 1000)

    # -- 7. record into the project ---------------------------------------
    if request.project_id and session is not None:
        _persist(session, request, answer, found)
    return answer


def _pick_llm(mode: Mode, trace: Trace):
    providers = registry.resolve("llm", settings.llm_provider)
    if not providers:
        raise ProviderUnavailable(
            "No language model is configured and even the extractive fallback failed to load."
        )
    chosen = providers[0]
    if mode.requires_reasoning_model and getattr(chosen, "is_extractive", False):
        raise ProviderUnavailable(
            f"'{mode.label}' needs a reasoning model. Set ANTHROPIC_API_KEY or "
            f"OPENAI_API_KEY, or use Quick answer / Deep research, which fall back to "
            f"quoting sources verbatim.",
            detail={"mode": mode.name},
        )
    if getattr(chosen, "is_extractive", False):
        trace.providers_unavailable.append(
            {
                "provider": "llm",
                "reason": "No reasoning model configured; answering by quoting sources verbatim.",
            }
        )
    return chosen


def _record_assumptions(trace: Trace, controls: ResearchControls, mode: Mode) -> None:
    if controls.date_from or controls.date_to:
        trace.assumptions.append(
            f"Restricted to sources published "
            f"{'from ' + str(controls.date_from) if controls.date_from else ''}"
            f"{' to ' + str(controls.date_to) if controls.date_to else ''}".strip()
        )
    if controls.academic_only:
        trace.assumptions.append("Academic sources only — the open web was not searched.")
    if controls.web_only:
        trace.assumptions.append("Web sources only — academic databases were not searched.")
    if controls.open_access_only:
        trace.assumptions.append(
            "Open-access only. Relevant paywalled work exists and is not represented here."
        )
    if not controls.include_preprints:
        trace.assumptions.append("Preprints excluded, so the most recent work may be missing.")
    if controls.domains_include:
        trace.assumptions.append("Restricted to: " + ", ".join(controls.domains_include))
    if controls.language:
        trace.assumptions.append(
            f"Searched in {controls.language}. Work published in other languages is not represented."
        )
    if not mode.use_web:
        trace.assumptions.append(f"'{mode.label}' does not search the open web.")


def _build_prompt(
    request: ResearchRequest,
    mode: Mode,
    sources: list[Source],
    context: list[dict],
    project_digest: str,
) -> str:
    lines: list[str] = []
    if project_digest:
        lines += [
            "Context about this research project (background only — do not cite it):",
            project_digest,
            "",
        ]
    lines.append(f"Question: {request.question}")
    lines.append("")
    lines.append("Sources retrieved for this question:")
    for label, sid in RetrievalSet.build(sources).labels.items():
        source = next(s for s in sources if s.id == sid)
        quality = source.quality
        lines.append(
            f"[{label}] {source.title}\n"
            f"      {', '.join(a.name for a in source.authors[:4]) or 'no named author'}"
            f" · {source.year or 'undated'}"
            f" · {source.container_title or source.site_name or 'unknown venue'}\n"
            f"      type={source.kind.value}; peer_reviewed={source.is_peer_reviewed}; "
            f"tier={quality.tier if quality else 'unappraised'}; "
            f"full_text={source.full_text_retrieved}"
            + (f"\n      caveats: {'; '.join(quality.caveats)}" if quality and quality.caveats else "")
        )
    lines.append("")
    lines.append("Passages (these are the only text you may cite):")
    for block in context:
        locator = f" {block['locator']}" if block["locator"] else ""
        lines.append(f"[{block['label']}{locator}] {block['text']}")
        lines.append("")
    lines.append(
        "Answer the question using only these passages. Return JSON matching the schema."
    )
    return "\n".join(lines)


def _empty_answer(request: ResearchRequest, mode: Mode, trace: Trace, started: float) -> Answer:
    """No sources. Say so — never fall back to answering from model memory."""
    reasons = [entry.get("reason", "") for entry in trace.providers_unavailable]
    summary = (
        "No sources could be retrieved for this question, so there is nothing to report. "
        "This answer is deliberately empty rather than generated from memory."
    )
    if reasons:
        summary += " Reasons: " + " ".join(reasons)
    answer = Answer(question=request.question, mode=mode.name, summary=summary, trace=trace)
    answer.warnings.append(
        "Nothing was retrieved. Check the Providers panel — a search provider may need "
        "configuring — or broaden the date range and source filters."
    )
    trace.limitations.append("No sources were retrieved.")
    trace.step("finish", "Returned an empty answer rather than an ungrounded one.",
               duration_ms=int((time.perf_counter() - started) * 1000))
    return answer


def _persist(session: Session, request: ResearchRequest, answer: Answer, found: list[Source]) -> None:
    """Store the turn, and keep the answer's citations pointing at the stored rows.

    Adding a source to a project assigns it a project-scoped id (the same paper
    can live in several projects), so the answer built a moment ago has to be
    re-pointed at those ids — otherwise clicking a citation would resolve to
    nothing.
    """
    from ..models import Message

    project_id = request.project_id
    assert project_id is not None

    remap: dict[str, str] = {}
    for source in found:
        previous = source.id
        record = memory_service.add_source(session, project_id, source, origin="search")
        if record.id != previous:
            remap[previous] = record.id

    if remap:
        for source in answer.sources:
            source.id = remap.get(source.id, source.id)
        for claim in answer.claims:
            for citation in claim.citations:
                citation.source_id = remap.get(citation.source_id, citation.source_id)
            claim.contested_by = [remap.get(sid, sid) for sid in claim.contested_by]
        for disagreement in answer.disagreements:
            for position in disagreement.positions:
                position.source_ids = [remap.get(sid, sid) for sid in position.source_ids]
        answer.trace.sources_selected = [
            remap.get(sid, sid) for sid in answer.trace.sources_selected
        ]

    session.add(
        Message(project_id=project_id, role="user", mode=answer.mode, content=request.question)
    )
    session.add(
        Message(
            project_id=project_id,
            role="assistant",
            mode=answer.mode,
            content=answer.summary,
            answer=answer.model_dump(mode="json"),
        )
    )
    memory_service.log_event(
        session,
        project_id,
        "research",
        f"{answer.mode}: {request.question[:120]}",
        sources=len(answer.sources),
        breakdown=answer.confidence_breakdown,
    )
    session.flush()


async def suggest_followups(answer: Answer) -> list[str]:
    """Concrete next steps, derived from what the answer actually lacks."""
    suggestions: list[str] = []
    if answer.disagreements:
        suggestions.append(
            f"Compare the sources that disagree about “{answer.disagreements[0].topic}”"
        )
    weak = [c for c in answer.claims if c.status.value == "ai_inference"]
    if weak:
        suggestions.append(f"Find sources for the {len(weak)} unsupported statement(s)")
    if answer.open_questions:
        suggestions.append(answer.open_questions[0])
    if any(not s.full_text_retrieved for s in answer.sources):
        suggestions.append("Read the full text of the abstract-only sources")
    if len(answer.sources) >= 3:
        suggestions.append("Build a comparison table of these papers")
        suggestions.append("Draw a diagram of the mechanism described")
    if answer.sources and all((s.year or 0) < date.today().year - 4 for s in answer.sources if s.year):
        suggestions.append("Restrict to the last five years")
    return suggestions[:6]
