"""Export a research answer to any supported format (spec §17)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ...core.errors import BadRequest, NotFound
from ...core.provenance import Answer
from ...db import get_session
from ...models import Message
from ...schemas import ExportIn
from ...services.export import FORMATS, export_answer

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/formats")
def formats() -> dict:
    return {
        "formats": [
            {"id": "pdf", "label": "PDF report"},
            {"id": "docx", "label": "Word document"},
            {"id": "md", "label": "Markdown"},
            {"id": "txt", "label": "Plain text"},
            {"id": "csv", "label": "Sources as CSV"},
            {"id": "xlsx", "label": "Excel workbook"},
            {"id": "pptx", "label": "Presentation slides"},
            {"id": "bibtex", "label": "BibTeX"},
            {"id": "ris", "label": "RIS (Zotero, EndNote)"},
            {"id": "json", "label": "JSON (full provenance)"},
        ],
        "note": "Every format keeps the citations, the source links and the confidence labels.",
    }


@router.post("")
def export(body: ExportIn, session: Session = Depends(get_session)) -> Response:
    if body.message_id:
        message = session.get(Message, body.message_id)
        if message is None or not message.answer:
            raise NotFound(f"No exportable answer on message '{body.message_id}'.")
        answer = Answer.model_validate(message.answer)
    elif body.answer:
        answer = Answer.model_validate(body.answer)
    else:
        raise BadRequest("Provide either 'message_id' or an 'answer' payload to export.")

    payload, media, filename = export_answer(
        answer, body.format, style=body.style, include_trace=body.include_trace  # type: ignore[arg-type]
    )
    return Response(
        content=payload,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
