"""Project memory (spec §13).

"According to the papers I uploaded earlier, what are the three biggest
limitations?" is answered by searching the project's own indexed corpus and
citing the passages that matched — not by trusting a model to remember.  The
answer therefore always shows which sources it used, and the user can tell at a
glance whether the retrieval actually found the right material.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..core.errors import NotFound
from ..core.provenance import Passage, Source
from ..core.registry import registry
from ..models import Message, Project, SourceRecord, TimelineEvent


@dataclass(slots=True)
class ProjectMemory:
    """Everything the workspace knows about one project."""

    project: Project
    sources: list[Source]
    recent_turns: list[dict[str, Any]]

    def source_by_id(self, sid: str) -> Source | None:
        return next((s for s in self.sources if s.id == sid), None)


def _index():
    return registry.require("passage_index", settings.index_provider)


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------
def get_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise NotFound(f"No project with id '{project_id}'.")
    return project


def load_sources(
    session: Session,
    project_id: str,
    *,
    include_excluded: bool = False,
    source_ids: list[str] | None = None,
) -> list[Source]:
    stmt = select(SourceRecord).where(SourceRecord.project_id == project_id)
    if not include_excluded:
        stmt = stmt.where(SourceRecord.excluded.is_(False))
    if source_ids:
        stmt = stmt.where(SourceRecord.id.in_(source_ids))
    records = session.execute(stmt.order_by(SourceRecord.added_at)).scalars().all()
    return [Source.model_validate(r.payload) for r in records]


def load_memory(session: Session, project_id: str, *, turns: int = 8) -> ProjectMemory:
    project = get_project(session, project_id)
    messages = (
        session.execute(
            select(Message)
            .where(Message.project_id == project_id)
            .order_by(Message.created_at.desc())
            .limit(turns * 2)
        )
        .scalars()
        .all()
    )
    recent = [
        {
            "role": m.role,
            "content": m.content,
            "mode": m.mode,
            "source_ids": [
                c["source_id"]
                for claim in ((m.answer or {}).get("claims") or [])
                for c in (claim.get("citations") or [])
            ]
            if m.answer
            else [],
            "created_at": m.created_at.isoformat(),
        }
        for m in reversed(messages)
    ]
    return ProjectMemory(
        project=project,
        sources=load_sources(session, project_id),
        recent_turns=recent,
    )


def recall(
    session: Session,
    project_id: str,
    query: str,
    *,
    limit: int = 14,
    source_ids: list[str] | None = None,
) -> list[Source]:
    """Search the project's own corpus, returning sources carrying the hit passages.

    The returned Sources hold *only* the matching passages, so a downstream
    prompt sees the evidence that actually matched rather than whole documents.
    """
    index = _index()
    passages: list[Passage] = index.search(project_id, query, limit=limit, source_ids=source_ids)
    if not passages:
        return []

    by_source: dict[str, list[Passage]] = {}
    for passage in passages:
        by_source.setdefault(passage.source_id, []).append(passage)

    records = (
        session.execute(
            select(SourceRecord).where(SourceRecord.id.in_(list(by_source)))
        )
        .scalars()
        .all()
    )
    out: list[Source] = []
    for record in records:
        if record.excluded:
            continue
        source = Source.model_validate(record.payload)
        source.passages = by_source.get(record.id, [])
        out.append(source)
    # Best-matching source first.
    out.sort(key=lambda s: max((p.score or 0) for p in s.passages), reverse=True)
    return out


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------
def add_source(
    session: Session,
    project_id: str,
    source: Source,
    *,
    origin: str = "search",
    blob_key: str | None = None,
    media_type: str | None = None,
    size_bytes: int | None = None,
) -> SourceRecord:
    """Add or merge a source, then index its passages for recall.

    De-duplication is by DOI/PMID/arXiv/URL identity, so the same paper arriving
    from OpenAlex and from a PDF upload becomes one source with the richer
    metadata of the two, not two entries the user has to reconcile.
    """
    identity = source.identity_key()
    existing = (
        session.execute(
            select(SourceRecord).where(
                SourceRecord.project_id == project_id,
                SourceRecord.identity_key == identity,
            )
        )
        .scalars()
        .first()
    )

    if existing is not None:
        stored = Source.model_validate(existing.payload)
        merged = _merge(stored, source)
        existing.payload = merged.model_dump(mode="json")
        existing.title = merged.title
        existing.url = merged.url
        existing.doi = merged.doi
        existing.quality_tier = merged.quality.tier if merged.quality else None
        existing.passage_count = len(merged.passages)
        if blob_key:
            existing.blob_key = blob_key
            existing.media_type = media_type
            existing.size_bytes = size_bytes
        session.flush()
        if source.passages:
            _index().add(project_id, merged.passages)
        return existing

    # A source id must be unique across the whole store, but the same paper can
    # legitimately live in several projects. Mint a fresh id for this project's
    # copy and re-point its passages at it, so citations stay resolvable.
    from ..core.provenance import new_id

    original_id = source.id
    source.id = new_id("src")
    for passage in source.passages:
        if passage.source_id == original_id:
            passage.source_id = source.id

    record = SourceRecord(
        id=source.id,
        project_id=project_id,
        kind=source.kind.value,
        title=source.title,
        url=source.url,
        doi=source.doi,
        identity_key=identity,
        payload=source.model_dump(mode="json"),
        quality_tier=source.quality.tier if source.quality else None,
        origin=origin,
        blob_key=blob_key,
        media_type=media_type,
        size_bytes=size_bytes,
        passage_count=len(source.passages),
    )
    session.add(record)
    session.flush()
    if source.passages:
        _index().add(project_id, source.passages)
    log_event(
        session, project_id, "source_added",
        f"Added source: {source.title[:120]}",
        source_id=record.id, origin=origin, source_kind=source.kind.value,
    )
    return record


def _merge(stored: Source, incoming: Source) -> Source:
    """Prefer whichever record actually has the field; never overwrite with None."""
    merged = stored.model_copy(deep=True)
    for field in (
        "doi", "pmid", "arxiv_id", "url", "container_title", "publisher", "published",
        "volume", "issue", "pages", "language", "license", "abstract", "is_open_access",
        "is_peer_reviewed", "retracted", "cited_by_count", "site_name",
    ):
        if getattr(merged, field, None) in (None, "", []) and getattr(incoming, field, None) not in (None, "", []):
            setattr(merged, field, getattr(incoming, field))
    if not merged.authors and incoming.authors:
        merged.authors = incoming.authors
    if incoming.full_text_retrieved and not merged.full_text_retrieved:
        merged.full_text_retrieved = True
        merged.retrieval_note = incoming.retrieval_note
    if incoming.passages:
        have = {p.fingerprint() for p in merged.passages}
        for passage in incoming.passages:
            if passage.fingerprint() not in have:
                passage.source_id = merged.id
                merged.passages.append(passage)
    merged.extra = {**incoming.extra, **merged.extra}
    if incoming.quality and not merged.quality:
        merged.quality = incoming.quality
    return merged


def remove_source(session: Session, project_id: str, source_id: str) -> None:
    record = session.get(SourceRecord, source_id)
    if record is None or record.project_id != project_id:
        raise NotFound(f"Source '{source_id}' is not in this project.")
    _index().remove_source(source_id)
    session.delete(record)
    log_event(session, project_id, "source_removed", f"Removed source: {record.title[:120]}")


def log_event(session: Session, project_id: str, kind: str, summary: str, **detail: Any) -> None:
    session.add(
        TimelineEvent(project_id=project_id, kind=kind, summary=summary, detail=detail)
    )


def context_digest(memory: ProjectMemory, *, limit: int = 30) -> str:
    """A compact description of the project, for prompting.

    Titles and metadata only — never passage text, which must come from an
    explicit retrieval step so that what the model sees is what gets cited.
    """
    lines = [f"Project: {memory.project.name}"]
    if memory.project.question:
        lines.append(f"Driving question: {memory.project.question}")
    if memory.sources:
        lines.append(f"\nSources already collected ({len(memory.sources)}):")
        for i, source in enumerate(memory.sources[:limit], start=1):
            tier = source.quality.tier if source.quality else "unappraised"
            lines.append(
                f"  {i}. {source.title[:110]} — {source.year or 'undated'}"
                f"{', ' + (source.container_title or '') if source.container_title else ''}"
                f" [{tier}{', full text' if source.full_text_retrieved else ', metadata only'}]"
            )
        if len(memory.sources) > limit:
            lines.append(f"  … and {len(memory.sources) - limit} more.")
    if memory.recent_turns:
        lines.append("\nRecent conversation:")
        for turn in memory.recent_turns[-6:]:
            lines.append(f"  {turn['role']}: {turn['content'][:220]}")
    return "\n".join(lines)
