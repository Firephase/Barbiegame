"""Video research (spec §3).

The transcript is the evidence.  Every claim the workspace makes about a video
is anchored to a caption window with a real timestamp, so the user can jump
straight to the moment and check it.
"""
from __future__ import annotations

from typing import Any

from ..config import settings
from ..core.errors import BadRequest
from ..core.provenance import Source, Trace
from ..core.registry import registry
from ..core.text import truncate
from ..providers.llm.base import LlmMessage, LlmRequest
from .grounding import RetrievalSet, verify_claim

SCHEMA = {
    "summary": "string — what the video covers, in a paragraph",
    "topics": [{"topic": "string", "start_seconds": 0, "why_it_matters": "string"}],
    "sections": [{"title": "string", "start_seconds": 0, "end_seconds": 0, "summary": "string"}],
    "claims": [
        {
            "text": "a factual claim the speaker makes",
            "status": "verified | interpretation | uncertain",
            "sources": ["S1"],
            "quote": "verbatim words from the transcript",
            "start_seconds": 0,
        }
    ],
    "questionable_claims": [
        {"claim": "string", "quote": "string", "why_questionable": "string", "start_seconds": 0}
    ],
    "difficult_concepts": [{"concept": "string", "explanation": "string", "start_seconds": 0}],
    "not_covered": ["things a viewer might expect but the video does not address"],
}

SYSTEM = """You analyse a video transcript for a researcher.

Ground rules:
- The transcript is all you have. You did not watch the video: you cannot describe
  slides, figures, gestures or anything not spoken.
- Every claim must quote the speaker verbatim and give the timestamp of the caption
  window it came from.
- "questionable_claims" is important: flag statements that are stated with more
  confidence than a transcript can justify, that contradict well-established
  findings, that generalise from a single study, or that are marketing rather than
  science. Explain why for each.
- Auto-generated captions garble technical terms. Where a word is clearly a
  mis-transcription, say so rather than analysing the mangled version.
- If the transcript does not cover the topic the user asked about, say that plainly."""


async def analyse(
    source: Source,
    *,
    question: str | None = None,
    trace: Trace | None = None,
) -> dict[str, Any]:
    if not source.passages:
        raise BadRequest(
            f"'{source.title}' has no transcript text, so there is nothing to analyse."
        )
    trace = trace or Trace()
    retrieval = RetrievalSet.build([source])

    # Feed the transcript with its timestamps intact.
    lines = []
    for passage in source.passages:
        lines.append(f"[S1 {passage.locator}] {passage.text}")
    transcript = truncate("\n".join(lines), 120_000)

    provider = registry.require("llm", settings.llm_provider)
    prompt = (
        f"Video: {source.title}\n"
        f"Channel: {source.publisher or 'unknown'}\n"
        f"Duration: {source.extra.get('duration_seconds', 'unknown')} seconds\n"
        f"Captions: {'auto-generated' if source.extra.get('auto_generated_captions') else 'publisher-supplied'}\n\n"
        + (f"The researcher asks: {question}\n\n" if question else "")
        + f"Transcript:\n{transcript}"
    )
    payload = await provider.complete_json(
        LlmRequest(
            messages=[LlmMessage(role="user", content=prompt)],
            system=SYSTEM,
            intent="video_analysis",
            json_schema=SCHEMA,
            max_tokens=7000,
            temperature=0.15,
            context_passages=retrieval.render_context(per_source=200, char_budget=120_000),
        )
    )

    video_id = source.extra.get("video_id")

    def stamp(seconds: Any) -> dict[str, Any]:
        try:
            secs = int(float(seconds))
        except (TypeError, ValueError):
            return {}
        m, s = divmod(secs, 60)
        h, m = divmod(m, 60)
        return {
            "start_seconds": secs,
            "timestamp": f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}",
            "url": f"https://www.youtube.com/watch?v={video_id}&t={secs}s" if video_id else None,
        }

    claims = []
    for raw in payload.get("claims") or []:
        if not isinstance(raw, dict):
            continue
        claim = verify_claim(raw, retrieval, trace)
        if claim.text:
            claims.append({**claim.model_dump(mode="json"), **stamp(raw.get("start_seconds"))})

    for key in ("topics", "sections", "difficult_concepts", "questionable_claims"):
        payload[key] = [
            {**row, **stamp(row.get("start_seconds"))}
            for row in (payload.get(key) or [])
            if isinstance(row, dict)
        ]

    warnings = []
    if source.extra.get("auto_generated_captions"):
        warnings.append(
            "Captions are auto-generated. Technical terms, names and numbers are often "
            "mis-transcribed, so quotes should be checked against the audio."
        )
    warnings.append(
        "This analysis is based on the transcript only — anything shown on screen but "
        "not spoken is not represented here."
    )

    return {
        "source_id": source.id,
        "title": source.title,
        "url": source.url,
        "duration_seconds": source.extra.get("duration_seconds"),
        **{k: v for k, v in payload.items() if k != "claims"},
        "claims": claims,
        "warnings": warnings,
        "trace": trace.model_dump(mode="json"),
    }


async def compare_with_literature(
    video_analysis: dict[str, Any],
    literature: list[Source],
    *,
    trace: Trace | None = None,
) -> dict[str, Any]:
    """Check a video's claims against retrieved papers (spec §3)."""
    if not literature:
        raise BadRequest("No literature was retrieved to compare the video against.")
    trace = trace or Trace()
    retrieval = RetrievalSet.build(literature)
    context = retrieval.render_context(per_source=4, char_budget=60_000)
    rendered = "\n\n".join(f"[{b['label']}] {b['title']}\n{b['text']}" for b in context)

    claims_text = "\n".join(
        f"- {c['text']} (at {c.get('timestamp', '?')})"
        for c in (video_analysis.get("claims") or [])[:25]
    )
    if not claims_text:
        raise BadRequest("The video analysis produced no claims to check.")

    provider = registry.require("llm", settings.llm_provider)
    payload = await provider.complete_json(
        LlmRequest(
            messages=[
                LlmMessage(
                    role="user",
                    content=(
                        f"Claims made in a video:\n{claims_text}\n\n"
                        f"Literature retrieved on the same topic:\n{rendered}\n\n"
                        "For each video claim, say whether the literature supports it, "
                        "contradicts it, or does not address it."
                    ),
                )
            ],
            system=(
                "You check spoken claims against retrieved literature.\n"
                "- Use only the labelled passages. Cite by label.\n"
                "- 'not addressed' is a common and legitimate verdict; use it rather than "
                "stretching a passage to fit.\n"
                "- A single paper agreeing is 'partially supported', not 'supported'."
            ),
            intent="fact_check",
            json_schema={
                "checks": [
                    {
                        "video_claim": "string",
                        "verdict": "supported | partially supported | contradicted | not addressed",
                        "sources": ["S1"],
                        "explanation": "string",
                    }
                ],
                "overall": "string",
            },
            max_tokens=5000,
            temperature=0.1,
            context_passages=context,
        )
    )
    checks = []
    for row in payload.get("checks") or []:
        if not isinstance(row, dict):
            continue
        ids = [s.id for s in (retrieval.source(str(r)) for r in row.get("sources") or []) if s]
        if row.get("verdict") in ("supported", "partially supported", "contradicted") and not ids:
            row["verdict"] = "not addressed"
            row["explanation"] = (
                (row.get("explanation") or "")
                + " (Downgraded: no retrieved source was cited for this verdict.)"
            ).strip()
        checks.append({**row, "source_ids": ids})

    trace.step("fact_check", f"Checked {len(checks)} video claims against {len(literature)} sources.")
    return {
        "checks": checks,
        "overall": payload.get("overall", ""),
        "sources": [s.model_dump(mode="json") for s in literature],
        "trace": trace.model_dump(mode="json"),
    }
