"""The anti-hallucination layer (spec §19).

Everything a model writes passes through ``verify_answer`` before it reaches
the user.  The rules enforced here are mechanical, not stylistic:

1. A citation may only name a source that was *actually retrieved this turn*.
   Unknown labels are stripped and recorded, never rendered.
2. A quoted passage must genuinely appear in the cited source.  A "quote" that
   does not occur in the retrieved text is removed.
3. A claim whose wording shares almost nothing with its cited passage is
   demoted from ``verified`` to ``interpretation`` or ``uncertain`` — the model
   does not get the final say on its own confidence.
4. A claim with no surviving citation becomes ``ai_inference`` and is labelled
   as such wherever it is displayed.
5. DOIs are only ever echoed from retrieved metadata.  A DOI the model typed
   that no retrieved source carries is deleted as fabricated.

The point is not that the model is untrustworthy in some abstract sense; it is
that a researcher must be able to check, and checking has to be cheap.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..core.provenance import (
    Answer,
    Citation,
    Claim,
    Disagreement,
    Epistemic,
    Passage,
    Position,
    Source,
    Trace,
)
from ..core.text import content_tokens, normalise, overlap_score

# A syntactically valid DOI. Shape alone proves nothing about existence, which
# is exactly why we additionally require it to come from retrieved metadata.
DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")
LABEL_RE = re.compile(r"\[?\b([Ss]\d{1,3})\b\]?")

#: Below this overlap, a "verified" claim is not treated as directly supported.
VERIFIED_FLOOR = 0.45
#: Below this, the citation is dropped entirely as unrelated.
SUPPORT_FLOOR = 0.18


@dataclass(slots=True)
class RetrievalSet:
    """The evidence available to a single turn — the universe of citable things."""

    sources: list[Source] = field(default_factory=list)
    #: Display label ("S1") -> source id.
    labels: dict[str, str] = field(default_factory=dict)

    @classmethod
    def build(cls, sources: list[Source]) -> "RetrievalSet":
        labels = {f"S{i}": src.id for i, src in enumerate(sources, start=1)}
        return cls(sources=sources, labels=labels)

    def label_for(self, source_id: str) -> str | None:
        return next((lbl for lbl, sid in self.labels.items() if sid == source_id), None)

    def source(self, ref: str) -> Source | None:
        """Resolve a label ("S3"), a source id, or a bare index."""
        ref = (ref or "").strip().strip("[]")
        sid = self.labels.get(ref) or self.labels.get(ref.upper())
        if sid is None and ref.isdigit():
            sid = self.labels.get(f"S{int(ref)}")
        if sid is None:
            sid = ref if any(s.id == ref for s in self.sources) else None
        return next((s for s in self.sources if s.id == sid), None) if sid else None

    def all_passages(self) -> list[Passage]:
        return [p for s in self.sources for p in s.passages]

    def known_dois(self) -> set[str]:
        return {s.doi.lower() for s in self.sources if s.doi}

    def render_context(self, *, per_source: int = 6, char_budget: int = 60_000) -> list[dict]:
        """Passages formatted for a prompt, with the labels the model must cite."""
        blocks: list[dict] = []
        used = 0
        for label, sid in self.labels.items():
            src = next((s for s in self.sources if s.id == sid), None)
            if src is None:
                continue
            chosen = sorted(
                src.passages, key=lambda p: (p.score is None, -(p.score or 0.0))
            )[:per_source] or ([] if not src.abstract else [
                Passage(source_id=src.id, text=src.abstract, section="Abstract")
            ])
            for p in chosen:
                if used + len(p.text) > char_budget:
                    return blocks
                used += len(p.text)
                blocks.append(
                    {
                        "label": label,
                        "source_id": src.id,
                        "passage_id": p.id,
                        "title": src.title,
                        "locator": p.locator,
                        "text": p.text,
                    }
                )
        return blocks


def _find_quote(quote: str, source: Source) -> Passage | None:
    """Return the passage containing ``quote`` — or None if it is not really there."""
    needle = normalise(quote).lower()
    if len(needle) < 12:
        return None
    for p in source.passages:
        if needle in normalise(p.text).lower():
            return p
    # Allow for light normalisation differences (quotes, ellipses, hyphenation).
    squashed = re.sub(r"[^a-z0-9]", "", needle)
    if len(squashed) < 20:
        return None
    for p in source.passages:
        if squashed in re.sub(r"[^a-z0-9]", "", normalise(p.text).lower()):
            return p
    return None


def _best_supporting_passage(text: str, source: Source) -> tuple[Passage | None, float]:
    best, best_score = None, 0.0
    for p in source.passages:
        score = overlap_score(text, p.text)
        if score > best_score:
            best, best_score = p, score
    if best is None and source.abstract:
        score = overlap_score(text, source.abstract)
        if score > best_score:
            best = Passage(source_id=source.id, text=source.abstract, section="Abstract")
            best_score = score
    return best, best_score


def verify_claim(raw: dict, retrieval: RetrievalSet, trace: Trace | None = None) -> Claim:
    """Turn one model-authored claim into a verified, citation-checked Claim."""
    text = normalise(str(raw.get("text") or raw.get("claim") or ""))
    declared = str(raw.get("status") or "").strip().lower()
    try:
        status = Epistemic(declared)
    except ValueError:
        status = Epistemic.INTERPRETATION

    refs = raw.get("sources") or raw.get("source_ids") or raw.get("citations") or []
    if isinstance(refs, str):
        refs = LABEL_RE.findall(refs) or [refs]

    citations: list[Citation] = []
    best_overall = 0.0
    dropped: list[str] = []

    for ref in refs:
        quote = None
        if isinstance(ref, dict):
            quote = ref.get("quote")
            ref = ref.get("source") or ref.get("source_id") or ref.get("label") or ""
        src = retrieval.source(str(ref))
        if src is None:
            # Rule 1: a citation to something that was never retrieved.
            dropped.append(str(ref))
            continue

        passage = _find_quote(quote, src) if quote else None
        quote_ok = passage is not None
        if passage is None:
            passage, score = _best_supporting_passage(text, src)
        else:
            score = max(overlap_score(text, passage.text), 0.5)

        if score < SUPPORT_FLOOR and not quote_ok:
            # Rule 3 (hard case): the cited source does not discuss this at all.
            dropped.append(f"{ref} (no supporting passage)")
            continue

        best_overall = max(best_overall, score)
        citations.append(
            Citation(
                source_id=src.id,
                passage_ids=[passage.id] if passage else [],
                # Rule 2: only echo a quote we located verbatim.
                quote=normalise(quote) if quote_ok else (passage.text[:400] if passage else None),
                locator=passage.locator if passage else None,
            )
        )

    note_parts: list[str] = []
    if dropped:
        note_parts.append(
            "Removed unsupported citation(s): " + ", ".join(dropped[:6]) + "."
        )

    # Rules 3-4: the verifier, not the model, sets the final epistemic status.
    if not citations:
        if status != Epistemic.AI_INFERENCE:
            note_parts.append(
                "No retrieved passage supports this, so it is marked as model inference "
                "rather than a finding."
            )
        status = Epistemic.AI_INFERENCE
    elif status == Epistemic.VERIFIED and best_overall < VERIFIED_FLOOR:
        status = Epistemic.INTERPRETATION
        note_parts.append(
            f"Wording overlaps its cited passage by only {best_overall:.0%}, so it is shown "
            "as an interpretation rather than a direct finding."
        )

    if trace is not None and dropped:
        trace.step(
            "verify",
            f"Dropped {len(dropped)} citation(s) that pointed outside the retrieved set.",
            claim=text[:160],
            dropped=dropped[:6],
        )

    return Claim(
        text=text,
        status=status,
        citations=citations,
        support_score=round(best_overall, 3) if citations else None,
        verification_note=" ".join(note_parts) or None,
    )


def strip_fabricated_dois(text: str, retrieval: RetrievalSet) -> tuple[str, list[str]]:
    """Delete DOIs the model produced that no retrieved source carries (rule 5)."""
    known = retrieval.known_dois()
    removed: list[str] = []

    def replace(match: re.Match) -> str:
        doi = match.group(0)
        if doi.lower().rstrip(".,;)") in known:
            return doi
        removed.append(doi)
        return "[DOI removed: not present in any retrieved source]"

    return DOI_RE.sub(replace, text), removed


def verify_answer(
    payload: dict,
    retrieval: RetrievalSet,
    *,
    question: str,
    mode: str,
    trace: Trace,
) -> Answer:
    """Build a fully-checked Answer from a model's structured output."""
    summary_raw = normalise(str(payload.get("summary") or ""))
    summary, bad_dois = strip_fabricated_dois(summary_raw, retrieval)

    answer = Answer(question=question, mode=mode, summary=summary, trace=trace)
    answer.sources = list(retrieval.sources)

    if bad_dois:
        answer.warnings.append(
            f"Removed {len(bad_dois)} DOI(s) from the summary that appear in no retrieved "
            f"source: {', '.join(bad_dois[:4])}. They were most likely fabricated."
        )
        trace.step("verify", "Removed DOIs absent from the retrieval set.", dois=bad_dois[:8])

    for raw in payload.get("claims") or []:
        if not isinstance(raw, dict):
            continue
        claim = verify_claim(raw, retrieval, trace)
        if claim.text:
            answer.claims.append(claim)

    for raw in payload.get("disagreements") or []:
        if not isinstance(raw, dict):
            continue
        positions = []
        for pos in raw.get("positions") or []:
            if not isinstance(pos, dict):
                continue
            ids = [
                s.id
                for s in (retrieval.source(str(r)) for r in (pos.get("sources") or []))
                if s is not None
            ]
            if pos.get("stance"):
                positions.append(
                    Position(stance=normalise(pos["stance"]), source_ids=ids, note=pos.get("note"))
                )
        if positions:
            answer.disagreements.append(
                Disagreement(
                    topic=normalise(str(raw.get("topic") or "Conflicting findings")),
                    positions=positions,
                    assessment=normalise(str(raw.get("assessment") or "")) or None,
                )
            )

    answer.open_questions = [
        normalise(str(q)) for q in (payload.get("open_questions") or []) if str(q).strip()
    ]
    trace.limitations.extend(
        normalise(str(x)) for x in (payload.get("limitations") or []) if str(x).strip()
    )

    _annotate_conflicts(answer)
    _add_coverage_warnings(answer, retrieval)
    return answer


def _annotate_conflicts(answer: Answer) -> None:
    """Link each claim to sources recorded as taking a different position."""
    for disagreement in answer.disagreements:
        for claim in answer.claims:
            cited = {c.source_id for c in claim.citations}
            if not cited:
                continue
            for position in disagreement.positions:
                if cited & set(position.source_ids):
                    continue
                others = [sid for sid in position.source_ids if sid not in cited]
                if others and any(
                    tok in content_tokens(claim.text)
                    for tok in content_tokens(disagreement.topic)[:6]
                ):
                    claim.contested_by = sorted(set(claim.contested_by) | set(others))
                    if claim.status == Epistemic.VERIFIED:
                        claim.status = Epistemic.UNCERTAIN
                        claim.verification_note = (
                            (claim.verification_note or "")
                            + " Other retrieved sources report a different result, so this is "
                              "shown as contested rather than settled."
                        ).strip()


def _add_coverage_warnings(answer: Answer, retrieval: RetrievalSet) -> None:
    """Say plainly when the evidence base is thin — do not let confidence outrun it."""
    if not retrieval.sources:
        answer.warnings.append(
            "No sources were retrieved for this question, so nothing in this answer is "
            "evidence-backed."
        )
        return

    grounded = [c for c in answer.claims if c.is_grounded]
    if answer.claims and not grounded:
        answer.warnings.append(
            "None of the statements above could be tied to a retrieved passage. Treat the "
            "whole answer as model inference."
        )

    single_source = [c for c in grounded if len({x.source_id for x in c.citations}) == 1]
    if len(single_source) == len(grounded) and len(retrieval.sources) > 1 and grounded:
        answer.warnings.append(
            "Every grounded statement rests on a single source. Nothing here has been "
            "corroborated across independent sources."
        )

    no_full_text = [s for s in retrieval.sources if not s.full_text_retrieved]
    if no_full_text and len(no_full_text) == len(retrieval.sources):
        answer.warnings.append(
            "Full text was not available for any source — this answer rests on abstracts "
            "and snippets only."
        )

    unread = [
        s.title for s in retrieval.sources
        if not s.passages and not s.abstract
    ]
    if unread:
        answer.warnings.append(
            f"{len(unread)} source(s) were listed but their content could not be read, so "
            "nothing was drawn from them."
        )
