"""Research, URL analysis, video analysis, papers and synthesis."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...config import settings
from ...core.errors import BadRequest
from ...core.provenance import Trace
from ...core.registry import registry
from ...db import get_session
from ...schemas import PaperAnalysisIn, ResearchIn, SynthesisIn, UrlIn, VideoIn
from ...services import memory, papers, video as video_service
from ...services.orchestrator import ResearchRequest, run_research, suggest_followups
from ...services.source_quality import appraise
from ...services.citations import format_all
from ..deps import load_source, require_reasoning_model

router = APIRouter(tags=["research"])


@router.post("/research")
async def research(body: ResearchIn, session: Session = Depends(get_session)) -> dict:
    """Ask a research question. Returns a verified, citation-checked answer."""
    answer = await run_research(
        ResearchRequest(
            question=body.question,
            project_id=body.project_id,
            mode=body.mode,
            controls=body.controls.to_controls(),
            source_ids=body.source_ids,
            use_project_only=body.use_project_only,
            force_search=body.force_search,
            depth=body.depth,
            level=body.level,
            citation_style=body.citation_style,
        ),
        session=session if body.project_id else None,
    )
    payload = answer.model_dump(mode="json")
    payload["citations"] = {
        source.id: format_all(source)[body.citation_style] for source in answer.sources
    }
    payload["confidence_breakdown"] = answer.confidence_breakdown
    payload["followups"] = await suggest_followups(answer)
    return payload


@router.post("/url")
async def analyse_url(body: UrlIn, session: Session = Depends(get_session)) -> dict:
    """Read a web page: summarise it, extract tables and references (spec §4)."""
    extractor = registry.require("url_extract", settings.extractor_provider)
    source = await extractor.extract(body.url)
    source.quality = appraise(source)

    if body.project_id:
        memory.get_project(session, body.project_id)
        record = memory.add_source(session, body.project_id, source, origin="url")
        source.id = record.id

    return {
        "source": source.model_dump(mode="json", exclude={"passages"}),
        "citations": format_all(source),
        "quality": source.quality.model_dump(mode="json"),
        "content": {
            "headings": source.extra.get("headings", []),
            "tables": source.extra.get("tables", []),
            "references": source.extra.get("linked_references", []),
            "word_count": source.extra.get("word_count"),
            "passage_count": len(source.passages),
            "preview": " ".join(p.text for p in source.passages[:3])[:2000],
        },
        "next": [
            "Ask a question about this page",
            "Compare it with the literature",
            "Extract its data into a chart",
        ],
    }


@router.post("/video")
async def analyse_video(body: VideoIn, session: Session = Depends(get_session)) -> dict:
    """Analyse a public video from its published captions (spec §3)."""
    provider = registry.require("video_transcript", settings.video_provider)
    source = await provider.fetch(body.url, languages=body.languages or None)
    source.quality = appraise(source)

    if body.project_id:
        memory.get_project(session, body.project_id)
        record = memory.add_source(session, body.project_id, source, origin="video")
        source.id = record.id

    require_reasoning_model("Video analysis")
    analysis = await video_service.analyse(source, question=body.question)
    return {
        "source": source.model_dump(mode="json", exclude={"passages"}),
        "citations": format_all(source),
        "transcript_segments": [
            {"text": p.text, "start_seconds": p.start_seconds, "timestamp": p.locator}
            for p in source.passages
        ],
        "analysis": analysis,
    }


@router.post("/video/fact-check")
async def fact_check_video(
    body: SynthesisIn, session: Session = Depends(get_session)
) -> dict:
    """Check a video's claims against the project's literature (spec §3)."""
    require_reasoning_model("Fact checking")
    sources = memory.load_sources(session, body.project_id, source_ids=body.source_ids or None)
    video_sources = [s for s in sources if s.kind.value == "video"]
    literature = [s for s in sources if s.kind.value != "video"]
    if not video_sources:
        raise BadRequest("No video in this project to check. Add one with POST /api/video first.")
    analysis = await video_service.analyse(video_sources[0], question=body.question)
    return await video_service.compare_with_literature(analysis, literature)


@router.post("/papers/analyse")
async def analyse_paper(body: PaperAnalysisIn, session: Session = Depends(get_session)) -> dict:
    """Explain one paper at a chosen level (spec §10)."""
    require_reasoning_model("Paper analysis")
    source = load_source(session, body.source_id, body.project_id)
    result = await papers.analyse(
        source, level=body.level, question=body.question, trace=Trace()
    )
    result["citations"] = format_all(source)
    result["quality"] = (source.quality or appraise(source)).model_dump(mode="json")
    return result


@router.post("/papers/synthesise")
async def synthesise_papers(body: SynthesisIn, session: Session = Depends(get_session)) -> dict:
    """Compare many papers side by side (spec §11)."""
    require_reasoning_model("Multi-paper synthesis")
    memory.get_project(session, body.project_id)
    sources = memory.load_sources(session, body.project_id, source_ids=body.source_ids or None)
    if not sources:
        raise BadRequest("This project has no sources to compare yet.")
    result = await papers.synthesise(sources, question=body.question)
    result["citations"] = {s.id: format_all(s) for s in sources}
    memory.log_event(
        session, body.project_id, "synthesis",
        f"Compared {len(sources)} papers.", source_ids=[s.id for s in sources],
    )
    return result
