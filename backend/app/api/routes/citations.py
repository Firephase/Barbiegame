"""Citation formatting and bibliography export (spec §2)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ...core.errors import BadRequest
from ...db import get_session
from ...schemas import CitationIn
from ...services import memory
from ...services.citations import STYLE_LABELS, STYLES, bibliography, format_all, in_text
from ...services.export import to_ris

router = APIRouter(prefix="/citations", tags=["citations"])


@router.get("/styles")
def styles() -> dict:
    return {"styles": [{"id": s, "label": STYLE_LABELS[s]} for s in STYLES]}


@router.post("/format")
def format_citations(body: CitationIn, session: Session = Depends(get_session)) -> dict:
    """Render citations for chosen sources in every supported style."""
    if not body.project_id:
        raise BadRequest("A project_id is required to look up sources.")
    sources = memory.load_sources(
        session, body.project_id, source_ids=body.source_ids or None, include_excluded=True
    )
    if not sources:
        raise BadRequest("None of the requested sources were found in this project.")
    numbering = {s.id: i for i, s in enumerate(sources, start=1)}
    return {
        "style": body.style,
        "items": [
            {
                "source_id": s.id,
                "title": s.title,
                "all_styles": format_all(s),
                "citation": format_all(s)[body.style],
                "in_text": in_text(s, body.style, index=numbering[s.id]),
            }
            for s in sources
        ],
        "bibliography": bibliography(sources, body.style),
    }


@router.post("/export")
def export_bibliography(
    body: CitationIn,
    fmt: str = "bibtex",
    session: Session = Depends(get_session),
) -> Response:
    """Download a citation file for a reference manager."""
    if not body.project_id:
        raise BadRequest("A project_id is required.")
    sources = memory.load_sources(
        session, body.project_id, source_ids=body.source_ids or None, include_excluded=True
    )
    if not sources:
        raise BadRequest("None of the requested sources were found in this project.")

    if fmt == "ris":
        payload, media, name = to_ris(sources), "application/x-research-info-systems", "references.ris"
    elif fmt == "bibtex":
        payload, media, name = bibliography(sources, "bibtex"), "application/x-bibtex", "references.bib"
    else:
        payload, media, name = bibliography(sources, body.style), "text/plain", "references.txt"
    return Response(
        content=payload.encode(),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
