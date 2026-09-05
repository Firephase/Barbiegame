"""Project workspaces (spec §12) — questions, sources, notes, timeline, map."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...config import settings
from ...core.errors import NotFound
from ...core.provenance import Source
from ...core.registry import registry
from ...db import get_session
from ...models import Artifact, Finding, Message, Note, Project, SourceRecord, TimelineEvent
from ...schemas import NoteIn, ProjectIn, ProjectOut, ProjectPatch
from ...services import knowledge_graph, memory
from ...services.citations import format_all

router = APIRouter(prefix="/projects", tags=["projects"])


def _counts(session: Session, project_id: str) -> dict:
    def count(model) -> int:
        return int(
            session.execute(
                select(func.count()).select_from(model).where(model.project_id == project_id)
            ).scalar_one()
        )

    index = registry.require("passage_index", settings.index_provider)
    return {
        "source_count": count(SourceRecord),
        "message_count": count(Message),
        "note_count": count(Note),
        "passage_count": index.count(project_id),
    }


def _out(session: Session, project: Project) -> ProjectOut:
    return ProjectOut(
        id=project.id, name=project.name, question=project.question,
        description=project.description, settings=project.settings or {},
        archived=project.archived, created_at=project.created_at,
        updated_at=project.updated_at, **_counts(session, project.id),
    )


@router.get("", response_model=list[ProjectOut])
def list_projects(
    session: Session = Depends(get_session),
    include_archived: bool = False,
) -> list[ProjectOut]:
    stmt = select(Project).order_by(Project.updated_at.desc())
    if not include_archived:
        stmt = stmt.where(Project.archived.is_(False))
    return [_out(session, p) for p in session.execute(stmt).scalars().all()]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, session: Session = Depends(get_session)) -> ProjectOut:
    project = Project(
        name=body.name, question=body.question,
        description=body.description, settings=body.settings,
    )
    session.add(project)
    session.flush()
    memory.log_event(session, project.id, "created", f"Project created: {project.name}")
    return _out(session, project)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, session: Session = Depends(get_session)) -> ProjectOut:
    return _out(session, memory.get_project(session, project_id))


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str, body: ProjectPatch, session: Session = Depends(get_session)
) -> ProjectOut:
    project = memory.get_project(session, project_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(project, field, value)
    session.flush()
    return _out(session, project)


@router.delete("/{project_id}", status_code=204, response_class=Response)
def delete_project(project_id: str, session: Session = Depends(get_session)) -> Response:
    project = memory.get_project(session, project_id)
    registry.require("passage_index", settings.index_provider).remove_project(project_id)
    session.delete(project)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------
@router.get("/{project_id}/sources")
def list_sources(
    project_id: str,
    session: Session = Depends(get_session),
    style: str = "apa",
    include_excluded: bool = False,
) -> dict:
    memory.get_project(session, project_id)
    stmt = select(SourceRecord).where(SourceRecord.project_id == project_id)
    if not include_excluded:
        stmt = stmt.where(SourceRecord.excluded.is_(False))
    records = session.execute(stmt.order_by(SourceRecord.added_at.desc())).scalars().all()

    items = []
    for record in records:
        source = Source.model_validate(record.payload)
        items.append(
            {
                **source.model_dump(mode="json", exclude={"passages"}),
                "passage_count": record.passage_count,
                "origin": record.origin,
                "starred": record.starred,
                "excluded": record.excluded,
                "added_at": record.added_at.isoformat(),
                "has_file": bool(record.blob_key),
                "citation": format_all(source)[style] if style in format_all(source) else None,
            }
        )
    return {"items": items, "total": len(items)}


@router.get("/{project_id}/sources/{source_id}")
def get_source(project_id: str, source_id: str, session: Session = Depends(get_session)) -> dict:
    record = session.get(SourceRecord, source_id)
    if record is None or record.project_id != project_id:
        raise NotFound(f"Source '{source_id}' is not in this project.")
    source = Source.model_validate(record.payload)
    return {
        **source.model_dump(mode="json"),
        "citations": format_all(source),
        "origin": record.origin,
        "starred": record.starred,
        "excluded": record.excluded,
        "has_file": bool(record.blob_key),
    }


@router.patch("/{project_id}/sources/{source_id}")
def update_source(
    project_id: str,
    source_id: str,
    starred: bool | None = None,
    excluded: bool | None = None,
    session: Session = Depends(get_session),
) -> dict:
    record = session.get(SourceRecord, source_id)
    if record is None or record.project_id != project_id:
        raise NotFound(f"Source '{source_id}' is not in this project.")
    if starred is not None:
        record.starred = starred
    if excluded is not None:
        record.excluded = excluded
    session.flush()
    return {"id": record.id, "starred": record.starred, "excluded": record.excluded}


@router.delete("/{project_id}/sources/{source_id}", status_code=204, response_class=Response)
def delete_source(
    project_id: str, source_id: str, session: Session = Depends(get_session)
) -> Response:
    memory.remove_source(session, project_id, source_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# conversation, notes, findings, timeline
# ---------------------------------------------------------------------------
@router.get("/{project_id}/messages")
def list_messages(
    project_id: str,
    session: Session = Depends(get_session),
    limit: int = Query(default=50, le=200),
) -> dict:
    memory.get_project(session, project_id)
    rows = (
        session.execute(
            select(Message)
            .where(Message.project_id == project_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": m.id, "role": m.role, "mode": m.mode, "content": m.content,
                "answer": m.answer, "created_at": m.created_at.isoformat(),
            }
            for m in reversed(rows)
        ]
    }


@router.get("/{project_id}/notes")
def list_notes(project_id: str, session: Session = Depends(get_session)) -> dict:
    memory.get_project(session, project_id)
    rows = (
        session.execute(
            select(Note).where(Note.project_id == project_id)
            .order_by(Note.pinned.desc(), Note.updated_at.desc())
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": n.id, "title": n.title, "body": n.body, "source_ids": n.source_ids,
                "tags": n.tags, "pinned": n.pinned,
                "created_at": n.created_at.isoformat(), "updated_at": n.updated_at.isoformat(),
            }
            for n in rows
        ]
    }


@router.post("/{project_id}/notes", status_code=201)
def create_note(project_id: str, body: NoteIn, session: Session = Depends(get_session)) -> dict:
    memory.get_project(session, project_id)
    note = Note(project_id=project_id, **body.model_dump())
    session.add(note)
    session.flush()
    return {"id": note.id}


@router.patch("/{project_id}/notes/{note_id}")
def update_note(
    project_id: str, note_id: str, body: NoteIn, session: Session = Depends(get_session)
) -> dict:
    note = session.get(Note, note_id)
    if note is None or note.project_id != project_id:
        raise NotFound(f"Note '{note_id}' is not in this project.")
    for field, value in body.model_dump().items():
        setattr(note, field, value)
    session.flush()
    return {"id": note.id}


@router.delete("/{project_id}/notes/{note_id}", status_code=204, response_class=Response)
def delete_note(
    project_id: str, note_id: str, session: Session = Depends(get_session)
) -> Response:
    note = session.get(Note, note_id)
    if note is None or note.project_id != project_id:
        raise NotFound(f"Note '{note_id}' is not in this project.")
    session.delete(note)
    return Response(status_code=204)


@router.get("/{project_id}/findings")
def list_findings(project_id: str, session: Session = Depends(get_session)) -> dict:
    memory.get_project(session, project_id)
    rows = (
        session.execute(
            select(Finding).where(Finding.project_id == project_id)
            .order_by(Finding.created_at.desc())
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {
                "id": f.id, "text": f.text, "status": f.status,
                "support_score": f.support_score, "citations": f.citations,
                "contested_by": f.contested_by, "created_at": f.created_at.isoformat(),
            }
            for f in rows
        ]
    }


@router.post("/{project_id}/findings", status_code=201)
def save_finding(project_id: str, claim: dict, session: Session = Depends(get_session)) -> dict:
    """Keep a verified claim as a project finding."""
    memory.get_project(session, project_id)
    finding = Finding(
        project_id=project_id,
        text=claim.get("text", ""),
        status=claim.get("status", "ai_inference"),
        support_score=claim.get("support_score"),
        citations=claim.get("citations", []),
        contested_by=claim.get("contested_by", []),
        message_id=claim.get("message_id"),
    )
    session.add(finding)
    session.flush()
    memory.log_event(session, project_id, "finding_saved", finding.text[:120])
    return {"id": finding.id}


@router.get("/{project_id}/timeline")
def timeline(
    project_id: str,
    session: Session = Depends(get_session),
    limit: int = Query(default=100, le=500),
) -> dict:
    memory.get_project(session, project_id)
    rows = (
        session.execute(
            select(TimelineEvent)
            .where(TimelineEvent.project_id == project_id)
            .order_by(TimelineEvent.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return {
        "items": [
            {"kind": e.kind, "summary": e.summary, "detail": e.detail,
             "created_at": e.created_at.isoformat()}
            for e in rows
        ]
    }


@router.get("/{project_id}/artifacts")
def list_artifacts(
    project_id: str, kind: str | None = None, session: Session = Depends(get_session)
) -> dict:
    memory.get_project(session, project_id)
    stmt = select(Artifact).where(Artifact.project_id == project_id)
    if kind:
        stmt = stmt.where(Artifact.kind == kind)
    rows = session.execute(stmt.order_by(Artifact.updated_at.desc())).scalars().all()
    return {
        "items": [
            {
                "id": a.id, "kind": a.kind, "title": a.title, "payload": a.payload,
                "source_ids": a.source_ids, "revision": a.revision,
                "created_at": a.created_at.isoformat(), "updated_at": a.updated_at.isoformat(),
            }
            for a in rows
        ]
    }


# ---------------------------------------------------------------------------
# research map (spec §14)
# ---------------------------------------------------------------------------
@router.get("/{project_id}/graph")
def project_graph(
    project_id: str,
    node: str | None = None,
    depth: int = Query(default=1, ge=1, le=3),
    session: Session = Depends(get_session),
) -> dict:
    """The project's knowledge graph, or the neighbourhood of one node."""
    from ...core.provenance import Answer

    project = memory.get_project(session, project_id)
    sources = memory.load_sources(session, project_id)
    answers = []
    for message in session.execute(
        select(Message).where(Message.project_id == project_id, Message.role == "assistant")
        .order_by(Message.created_at.desc()).limit(25)
    ).scalars().all():
        if message.answer:
            try:
                answers.append(Answer.model_validate(message.answer))
            except Exception:
                continue

    graph = knowledge_graph.build(sources, answers=answers, question=project.question or None)
    if node:
        graph = knowledge_graph.neighbourhood(graph, node, depth=depth)
    return graph.to_dict()


@router.get("/{project_id}/recall")
def recall(
    project_id: str,
    q: str = Query(min_length=2),
    limit: int = Query(default=12, le=50),
    session: Session = Depends(get_session),
) -> dict:
    """Search this project's own corpus (spec §13)."""
    memory.get_project(session, project_id)
    sources = memory.recall(session, project_id, q, limit=limit)
    return {
        "query": q,
        "items": [
            {
                "source_id": s.id,
                "title": s.title,
                "url": s.url,
                "year": s.year,
                "quality_tier": s.quality.tier if s.quality else None,
                "passages": [
                    {"id": p.id, "text": p.text, "locator": p.locator, "score": p.score}
                    for p in s.passages
                ],
            }
            for s in sources
        ],
        "note": "These are the passages that matched, from sources already in this project.",
    }
