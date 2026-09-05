"""Paper analysis (§10) and multi-paper synthesis (§11).

Structure extraction is done in two passes: a deterministic section splitter
that works on the real text (headings, IMRaD keywords), then a model pass that
fills the analytical fields — each of which must point at a passage in the
paper, so "sample size: 42" is checkable rather than asserted.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from ..config import settings
from ..core.errors import BadRequest
from ..core.provenance import Passage, Source, Trace
from ..core.registry import registry
from ..core.text import normalise, truncate
from ..providers.llm.base import LlmMessage, LlmRequest
from .grounding import RetrievalSet, verify_claim

Level = Literal["beginner", "student", "researcher", "expert"]

LEVEL_GUIDE: dict[str, str] = {
    "beginner": (
        "Explain to someone meeting this field for the first time. Define every term "
        "the first time it appears. Use everyday analogies, and say plainly what the "
        "researchers were trying to find out and what they think they found."
    ),
    "student": (
        "Explain to an undergraduate who knows the basics. Keep technical terms but "
        "gloss them. Be explicit about why the method suits the question."
    ),
    "researcher": (
        "Explain to a working researcher in an adjacent field. Assume methodological "
        "literacy. Focus on design choices, controls, effect sizes and what the "
        "statistics do and do not license."
    ),
    "expert": (
        "Explain to a specialist. Be terse. Concentrate on what is novel, what is "
        "contestable, the adequacy of controls, and how it sits against prior work."
    ),
}

# IMRaD-ish section detection on real headings.
_SECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("abstract", re.compile(r"^\s*(abstract|summary)\b", re.I)),
    ("introduction", re.compile(r"^\s*(\d+\.?\s*)?(introduction|background)\b", re.I)),
    ("methods", re.compile(r"^\s*(\d+\.?\s*)?(methods?|materials and methods|methodology|experimental( procedures| section)?)\b", re.I)),
    ("results", re.compile(r"^\s*(\d+\.?\s*)?(results?|findings)\b", re.I)),
    ("discussion", re.compile(r"^\s*(\d+\.?\s*)?discussion\b", re.I)),
    ("limitations", re.compile(r"^\s*(\d+\.?\s*)?(limitations?|strengths and limitations)\b", re.I)),
    ("conclusion", re.compile(r"^\s*(\d+\.?\s*)?(conclusions?|concluding remarks)\b", re.I)),
    ("references", re.compile(r"^\s*(\d+\.?\s*)?(references|bibliography|works cited)\b", re.I)),
    ("acknowledgements", re.compile(r"^\s*acknowledg", re.I)),
    ("funding", re.compile(r"^\s*(funding|financial support|conflicts? of interest|competing interests)\b", re.I)),
]

_FIGURE_RE = re.compile(r"\b(fig(?:ure)?\.?\s*\d+[a-z]?)", re.I)
_TABLE_RE = re.compile(r"\b(table\s*\d+[a-z]?)", re.I)
_N_RE = re.compile(r"\b[nN]\s*=\s*(\d[\d,]*)")
_P_RE = re.compile(r"\bp\s*[<=>]\s*0?\.\d+", re.I)
_CI_RE = re.compile(r"\b95%\s*(?:CI|confidence interval)", re.I)
_STAT_TERMS = (
    "t-test", "anova", "chi-square", "chi squared", "mann-whitney", "wilcoxon",
    "kruskal", "regression", "cox proportional", "kaplan-meier", "log-rank",
    "bonferroni", "benjamini", "fdr", "bayesian", "mixed model", "permutation test",
)


def split_sections(source: Source) -> dict[str, list[Passage]]:
    """Group a paper's passages into IMRaD sections using its real headings."""
    sections: dict[str, list[Passage]] = {}
    current = "front_matter"
    for passage in source.passages:
        heading = passage.section or passage.text[:80]
        for name, pattern in _SECTION_PATTERNS:
            if pattern.match(heading):
                current = name
                break
        sections.setdefault(current, []).append(passage)
    return sections


def structural_facts(source: Source) -> dict[str, Any]:
    """Everything we can establish about a paper without asking a model."""
    text = " ".join(p.text for p in source.passages)
    sections = split_sections(source)
    sample_sizes = [int(m.replace(",", "")) for m in _N_RE.findall(text)][:20]
    return {
        "sections_found": sorted(sections),
        "section_lengths": {k: sum(len(p.text) for p in v) for k, v in sections.items()},
        "figures_referenced": sorted({m.lower() for m in _FIGURE_RE.findall(text)})[:40],
        "tables_referenced": sorted({m.lower() for m in _TABLE_RE.findall(text)})[:40],
        "sample_sizes_mentioned": sample_sizes,
        "largest_n_mentioned": max(sample_sizes) if sample_sizes else None,
        "p_values_reported": len(_P_RE.findall(text)),
        "reports_confidence_intervals": bool(_CI_RE.search(text)),
        "statistical_methods_mentioned": sorted(
            {term for term in _STAT_TERMS if term in text.lower()}
        ),
        "has_limitations_section": "limitations" in sections,
        "has_funding_statement": "funding" in sections,
        "word_count": len(text.split()),
        "full_text_available": source.full_text_retrieved,
    }


ANALYSIS_SCHEMA = {
    "research_question": "string",
    "hypothesis": "string or null if none is stated",
    "background": "string",
    "methods": "string",
    "experimental_design": "string",
    "results": "string",
    "statistical_methods": "string",
    "limitations": ["string"],
    "conclusions": "string",
    "key_references": ["string"],
    "claims": [
        {
            "text": "a specific factual claim the paper makes",
            "status": "verified | interpretation | uncertain",
            "sources": ["S1"],
            "quote": "verbatim sentence from the paper supporting it",
        }
    ],
    "what_it_does_not_show": ["string"],
}

ANALYSIS_SYSTEM = """You analyse a single research paper for a researcher who has not read it.

Ground rules:
- Use ONLY the passages provided. They are labelled [S1] and are the whole paper you have.
- Every entry in "claims" must quote a verbatim sentence from those passages.
- If a field is genuinely not stated in the paper (no hypothesis, no limitations
  section), write "Not stated in the text provided" rather than supplying a plausible one.
- "what_it_does_not_show" is where you push back: name the conclusions readers
  commonly over-draw from a study of this design.
- Never state a number the passages do not contain."""


async def analyse(
    source: Source,
    *,
    level: Level = "researcher",
    question: str | None = None,
    trace: Trace | None = None,
) -> dict[str, Any]:
    """Full structured analysis of one paper."""
    if not source.passages and not source.abstract:
        raise BadRequest(
            f"'{source.title}' has no readable text, so it cannot be analysed. "
            "If it is a scanned PDF, run OCR on it first."
        )

    facts = structural_facts(source)
    trace = trace or Trace()
    trace.step("analyse_paper", f"Split '{truncate(source.title, 60)}' into "
                                f"{len(facts['sections_found'])} section(s).", **facts)

    retrieval = RetrievalSet.build([source])
    context = retrieval.render_context(per_source=40, char_budget=90_000)
    rendered = "\n\n".join(
        f"[{b['label']}{(' ' + b['locator']) if b['locator'] else ''}] {b['text']}" for b in context
    )

    provider = registry.require("llm", settings.llm_provider)
    prompt = (
        f"{LEVEL_GUIDE[level]}\n\n"
        f"Paper: {source.title}\n"
        f"{'Authors: ' + ', '.join(a.name for a in source.authors[:8]) if source.authors else ''}\n"
        f"{'Published: ' + str(source.published) if source.published else 'Publication date unknown'}\n"
        f"{'Venue: ' + source.container_title if source.container_title else ''}\n"
        f"Peer reviewed: {source.is_peer_reviewed}\n\n"
        f"{'Focus especially on: ' + question if question else ''}\n\n"
        f"Passages:\n{rendered}"
    )
    payload = await provider.complete_json(
        LlmRequest(
            messages=[LlmMessage(role="user", content=prompt)],
            system=ANALYSIS_SYSTEM,
            intent="paper_analysis",
            json_schema=ANALYSIS_SCHEMA,
            max_tokens=6000,
            temperature=0.1,
            context_passages=context,
        )
    )

    claims = [
        verify_claim(raw, retrieval, trace).model_dump(mode="json")
        for raw in (payload.get("claims") or [])
        if isinstance(raw, dict)
    ]

    warnings: list[str] = []
    if not source.full_text_retrieved:
        warnings.append(
            "Only the abstract or a snippet of this paper was available, so this analysis "
            "cannot speak to its methods or results in detail."
        )
    if not facts["has_limitations_section"] and facts["full_text_available"]:
        warnings.append("The paper has no limitations section — the caveats below are inferred.")
    if source.retracted:
        warnings.append("This work is flagged as retracted or corrected.")
    if source.is_peer_reviewed is False:
        warnings.append("Preprint — these findings have not been peer reviewed.")

    return {
        "source_id": source.id,
        "title": source.title,
        "level": level,
        "structure": facts,
        "analysis": {k: v for k, v in payload.items() if k != "claims"},
        "claims": claims,
        "warnings": warnings,
        "trace": trace.model_dump(mode="json"),
    }


SYNTHESIS_SCHEMA = {
    "overview": "string — what this body of work collectively shows",
    "comparison": [
        {
            "source": "S1",
            "research_question": "string",
            "model_or_system": "string, e.g. mouse xenograft, human cohort, in vitro",
            "methods": "string",
            "sample_size": "string, or 'not reported'",
            "intervention_or_exposure": "string",
            "main_findings": "string",
            "limitations": "string",
        }
    ],
    "agreements": [{"statement": "string", "sources": ["S1", "S2"]}],
    "contradictions": [
        {
            "topic": "string",
            "positions": [{"stance": "string", "sources": ["S1"], "note": "string"}],
            "assessment": "why they may differ — design, population, dose, endpoint",
        }
    ],
    "strongly_supported": [{"statement": "string", "sources": ["S1", "S2"], "why": "string"}],
    "weakly_supported": [{"statement": "string", "sources": ["S3"], "why": "string"}],
    "research_gaps": ["string"],
}

SYNTHESIS_SYSTEM = """You compare a set of research papers for a researcher building a picture of a field.

Ground rules:
- Use ONLY the labelled passages given. Cite by label ([S1], [S2]).
- Fill "sample_size" and every other field from the text; write "not reported" when
  the passages do not state it. Never estimate a number.
- Contradictions matter more than agreements: look actively for results that do
  not line up, and explain what could produce the difference (population, dose,
  endpoint, model system, statistical approach) rather than declaring a winner.
- "strongly_supported" requires independent corroboration across sources; a claim
  resting on one paper belongs in "weakly_supported", however emphatic that paper is.
- Note when studies share authors, funders, or a cohort — that is not independence."""


async def synthesise(
    sources: list[Source],
    *,
    question: str | None = None,
    trace: Trace | None = None,
) -> dict[str, Any]:
    """Structured comparison across many papers (spec §11)."""
    usable = [s for s in sources if s.passages or s.abstract]
    if len(usable) < 2:
        raise BadRequest(
            f"Synthesis needs at least two readable papers; {len(usable)} of "
            f"{len(sources)} supplied had text available."
        )

    trace = trace or Trace()
    retrieval = RetrievalSet.build(usable)
    budget = max(12_000, 110_000 // max(len(usable), 1))
    context = retrieval.render_context(per_source=max(3, 30 // len(usable)), char_budget=110_000)

    grouped: dict[str, list[str]] = {}
    for block in context:
        grouped.setdefault(block["label"], []).append(block["text"])

    rendered_parts = []
    for label, sid in retrieval.labels.items():
        src = next(s for s in usable if s.id == sid)
        header = (
            f"[{label}] {src.title}\n"
            f"  Authors: {', '.join(a.name for a in src.authors[:6]) or 'unknown'}\n"
            f"  Year: {src.year or 'unknown'} | Venue: {src.container_title or 'unknown'} | "
            f"Peer reviewed: {src.is_peer_reviewed} | Full text: {src.full_text_retrieved}"
        )
        body = truncate("\n".join(grouped.get(label, [])) or (src.abstract or ""), budget)
        rendered_parts.append(f"{header}\n  ---\n{body}")

    provider = registry.require("llm", settings.llm_provider)
    payload = await provider.complete_json(
        LlmRequest(
            messages=[
                LlmMessage(
                    role="user",
                    content=(
                        f"{'Research question: ' + question if question else 'Compare these papers.'}\n\n"
                        + "\n\n".join(rendered_parts)
                    ),
                )
            ],
            system=SYNTHESIS_SYSTEM,
            intent="synthesis",
            json_schema=SYNTHESIS_SCHEMA,
            max_tokens=8000,
            temperature=0.15,
            context_passages=context,
        )
    )

    # Resolve every label the model used back to a real source id — anything that
    # does not resolve is dropped rather than displayed.
    def resolve(refs: Any) -> list[str]:
        out = []
        for ref in refs or []:
            src = retrieval.source(str(ref))
            if src:
                out.append(src.id)
        return out

    comparison = []
    for row in payload.get("comparison") or []:
        if not isinstance(row, dict):
            continue
        src = retrieval.source(str(row.get("source", "")))
        if src is None:
            continue
        comparison.append({**row, "source_id": src.id, "title": src.title,
                           "year": src.year, "peer_reviewed": src.is_peer_reviewed})

    def resolve_list(key: str) -> list[dict]:
        out = []
        for row in payload.get(key) or []:
            if isinstance(row, dict) and row.get("statement"):
                ids = resolve(row.get("sources"))
                if ids:
                    out.append({**row, "source_ids": ids})
        return out

    contradictions = []
    for row in payload.get("contradictions") or []:
        if not isinstance(row, dict):
            continue
        positions = [
            {**p, "source_ids": resolve(p.get("sources"))}
            for p in (row.get("positions") or [])
            if isinstance(p, dict) and p.get("stance")
        ]
        if len(positions) >= 2:
            contradictions.append({**row, "positions": positions})

    strongly = resolve_list("strongly_supported")
    weakly = resolve_list("weakly_supported")
    # Independence check the model does not get to skip: a "strongly supported"
    # claim resting on one source is demoted here, mechanically.
    demoted = [row for row in strongly if len(set(row["source_ids"])) < 2]
    strongly = [row for row in strongly if len(set(row["source_ids"])) >= 2]
    for row in demoted:
        row["why"] = (row.get("why", "") + " (Moved: only one source supports this.)").strip()
    weakly.extend(demoted)

    warnings: list[str] = []
    if demoted:
        warnings.append(
            f"{len(demoted)} statement(s) were moved from strongly to weakly supported "
            "because only one source backed them."
        )
    abstract_only = [s.title for s in usable if not s.full_text_retrieved]
    if abstract_only:
        warnings.append(
            f"{len(abstract_only)} of {len(usable)} papers were compared from their abstracts "
            "alone; methods and limitations for those are not fully represented."
        )
    shared_authors = _shared_authors(usable)
    if shared_authors:
        warnings.append(
            "These papers are not fully independent — shared author(s): "
            + ", ".join(shared_authors[:5]) + "."
        )

    trace.step("synthesise", f"Compared {len(usable)} papers.",
               sources=[s.id for s in usable], demoted=len(demoted))

    return {
        "question": question,
        "overview": normalise(str(payload.get("overview") or "")),
        "comparison": comparison,
        "agreements": resolve_list("agreements"),
        "contradictions": contradictions,
        "strongly_supported": strongly,
        "weakly_supported": weakly,
        "research_gaps": [normalise(str(g)) for g in (payload.get("research_gaps") or [])],
        "sources": [s.model_dump(mode="json") for s in usable],
        "warnings": warnings,
        "trace": trace.model_dump(mode="json"),
    }


def _shared_authors(sources: list[Source]) -> list[str]:
    counts: dict[str, int] = {}
    for source in sources:
        for author in {a.name.lower() for a in source.authors}:
            counts[author] = counts.get(author, 0) + 1
    return sorted(name.title() for name, n in counts.items() if n > 1)
