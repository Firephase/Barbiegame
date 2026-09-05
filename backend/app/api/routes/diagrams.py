"""Diagram generation and iterative revision (spec §7)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...core.errors import NotFound
from ...db import get_session
from ...models import Artifact
from ...schemas import DiagramIn, DiagramReviseIn
from ...services import diagrams as diagram_service
from ...services import memory
from ..deps import require_reasoning_model

router = APIRouter(prefix="/diagrams", tags=["diagrams"])


@router.get("/kinds")
def kinds() -> dict:
    return {
        "kinds": [
            {"id": "pathway", "label": "Biological pathway"},
            {"id": "workflow", "label": "Experimental workflow"},
            {"id": "mechanism", "label": "Mechanism"},
            {"id": "process", "label": "Process diagram"},
            {"id": "flowchart", "label": "Flowchart"},
            {"id": "concept_map", "label": "Concept map"},
            {"id": "molecular_workflow", "label": "Molecular biology workflow"},
            {"id": "framework", "label": "Research framework"},
            {"id": "timeline", "label": "Timeline"},
            {"id": "decision_tree", "label": "Decision tree"},
            {"id": "architecture", "label": "System architecture"},
            {"id": "knowledge_graph", "label": "Knowledge graph"},
            {"id": "sequence", "label": "Sequence diagram"},
            {"id": "state", "label": "State diagram"},
        ],
        "renderer": "mermaid",
        "revision_examples": [
            "Add a step for the repair pathway",
            "Remove the validation section",
            "Make it simpler",
            "Label every arrow",
            "Lay it out left to right",
            "Make it suitable for a scientific presentation",
        ],
    }


@router.post("")
async def create_diagram(body: DiagramIn, session: Session = Depends(get_session)) -> dict:
    require_reasoning_model("Diagram generation")
    context = ""
    if body.project_id and body.source_ids:
        sources = memory.load_sources(session, body.project_id, source_ids=body.source_ids)
        context = "\n\n".join(
            f"{s.title}\n" + " ".join(p.text for p in s.passages[:4])[:3000] for s in sources
        )

    description = body.description
    if body.presentation_ready:
        description += "\n\n" + diagram_service.PRESENTATION_HINT

    diagram = await diagram_service.generate(
        description, kind=body.kind, title=body.title, context=context  # type: ignore[arg-type]
    )
    payload = diagram.to_dict()

    if body.project_id:
        artifact = Artifact(
            id=diagram.id, project_id=body.project_id, kind="diagram",
            title=diagram.title, payload=payload, source_ids=body.source_ids,
        )
        session.add(artifact)
        memory.log_event(session, body.project_id, "diagram", f"Diagram: {diagram.title[:100]}")
        session.flush()
    return payload


@router.post("/{diagram_id}/revise")
async def revise_diagram(
    diagram_id: str, body: DiagramReviseIn, session: Session = Depends(get_session)
) -> dict:
    """Iteratively modify a diagram in natural language."""
    require_reasoning_model("Diagram revision")
    artifact = session.get(Artifact, diagram_id)
    if artifact is None or artifact.kind != "diagram":
        raise NotFound(f"No diagram with id '{diagram_id}'.")

    stored = artifact.payload
    diagram = diagram_service.Diagram(
        id=artifact.id, kind=stored.get("kind", "flowchart"), title=stored.get("title", ""),
        source=stored.get("source", ""), dialect=stored.get("dialect", "flowchart TD"),
        revision=artifact.revision,
    )
    revised = await diagram_service.revise(diagram, body.instruction)
    artifact.payload = revised.to_dict()
    artifact.revision = revised.revision
    session.flush()
    return artifact.payload
