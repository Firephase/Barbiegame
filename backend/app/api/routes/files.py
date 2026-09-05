"""File and image ingestion (spec §5, §9, §10)."""
from __future__ import annotations

import base64

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ...core.errors import BadRequest, NotFound
from ...core.provenance import Source, SourceKind
from ...db import get_session
from ...models import Artifact, SourceRecord
from ...services import images as image_service
from ...services import memory
from ...services.citations import format_all
from ...services.source_quality import appraise
from ..deps import load_source_record, parser_for, read_upload, require_reasoning_model, storage

router = APIRouter(tags=["files"])

IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}


@router.post("/files")
async def upload_files(
    project_id: str = Form(...),
    files: list[UploadFile] = File(...),
    session: Session = Depends(get_session),
) -> dict:
    """Upload papers, datasets, notes or images into a project."""
    memory.get_project(session, project_id)
    blobs = storage()
    results, failures = [], []

    for upload in files:
        filename = upload.filename or "upload"
        try:
            data = await read_upload(upload)
            stored = blobs.put(data, filename)
            media_type = upload.content_type or stored.media_type

            if media_type in IMAGE_TYPES:
                source = Source(
                    kind=SourceKind.IMAGE,
                    title=filename,
                    retrieved_by="upload",
                    full_text_retrieved=False,
                    retrieval_note="Image stored. Its content is only described once analysed.",
                    extra={"media_type": media_type, "bytes": stored.size},
                )
            else:
                parser = parser_for(filename)
                source = parser.parse(data, filename)

            source.quality = appraise(source)
            record = memory.add_source(
                session, project_id, source, origin="upload",
                blob_key=stored.key, media_type=media_type, size_bytes=stored.size,
            )
            results.append(
                {
                    "source_id": record.id,
                    "filename": filename,
                    "kind": source.kind.value,
                    "passages": len(source.passages),
                    "media_type": media_type,
                    "bytes": stored.size,
                    "note": source.retrieval_note,
                    "sheets": source.extra.get("sheets"),
                }
            )
        except Exception as exc:  # noqa: BLE001 — one bad file must not lose the batch
            failures.append({"filename": filename, "error": str(exc)})

    return {
        "uploaded": results,
        "failed": failures,
        "summary": f"{len(results)} file(s) added"
        + (f", {len(failures)} failed" if failures else "")
        + ".",
    }


@router.get("/files/{source_id}/raw")
def download_file(source_id: str, session: Session = Depends(get_session)) -> Response:
    record = load_source_record(session, source_id)
    if not record.blob_key:
        raise NotFound(f"'{record.title}' has no stored file.")
    return Response(
        content=storage().read(record.blob_key),
        media_type=record.media_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{record.title}"'},
    )


@router.get("/files/{source_id}/passages")
def source_passages(
    source_id: str, limit: int = 200, session: Session = Depends(get_session)
) -> dict:
    record = load_source_record(session, source_id)
    source = Source.model_validate(record.payload)
    return {
        "source_id": source_id,
        "title": source.title,
        "total": len(source.passages),
        "items": [
            {"id": p.id, "text": p.text, "page": p.page, "section": p.section,
             "locator": p.locator}
            for p in source.passages[:limit]
        ],
    }


# ---------------------------------------------------------------------------
# images (spec §5, §6)
# ---------------------------------------------------------------------------
def _image_input(record: SourceRecord, label: str, kind: str = "auto") -> image_service.ImageInput:
    if not record.blob_key:
        raise BadRequest(f"'{record.title}' has no stored image file.")
    return image_service.ImageInput(
        label=label,
        data=storage().read(record.blob_key),
        media_type=record.media_type or "image/png",
        filename=record.title,
        kind=kind,  # type: ignore[arg-type]
    )


@router.post("/images/{source_id}/analyse")
async def analyse_image(
    source_id: str,
    question: str | None = None,
    kind: str = "auto",
    session: Session = Depends(get_session),
) -> dict:
    """Analyse a stored image, keeping observation apart from interpretation."""
    require_reasoning_model("Image analysis")
    record = load_source_record(session, source_id)
    result = await image_service.analyse(
        _image_input(record, "IMG1", kind), question=question, kind=kind  # type: ignore[arg-type]
    )
    session.add(
        Artifact(
            project_id=record.project_id, kind="image_analysis",
            title=f"Analysis of {record.title}", payload=result, source_ids=[source_id],
        )
    )
    session.flush()
    return result


@router.post("/images/compare")
async def compare_images(
    source_ids: list[str],
    question: str | None = None,
    session: Session = Depends(get_session),
) -> dict:
    """Compare several stored images in one context (spec §6)."""
    require_reasoning_model("Image comparison")
    if len(source_ids) < 2:
        raise BadRequest("Comparison needs at least two images.")
    records = [load_source_record(session, sid) for sid in source_ids]
    inputs = [_image_input(r, f"IMG{i}") for i, r in enumerate(records, start=1)]
    result = await image_service.compare(inputs, question=question)
    session.add(
        Artifact(
            project_id=records[0].project_id, kind="image_comparison",
            title=f"Comparison of {len(records)} images", payload=result, source_ids=source_ids,
        )
    )
    session.flush()
    return result


@router.post("/images/analyse-upload")
async def analyse_uploaded_image(
    file: UploadFile = File(...),
    question: str | None = Form(default=None),
    kind: str = Form(default="auto"),
) -> dict:
    """Analyse an image without storing it in a project."""
    require_reasoning_model("Image analysis")
    data = await read_upload(file)
    media_type = file.content_type or "image/png"
    if media_type not in IMAGE_TYPES:
        raise BadRequest(f"'{file.filename}' is {media_type}, which is not a supported image type.")
    return await image_service.analyse(
        image_service.ImageInput(
            label="IMG1", data=data, media_type=media_type,
            filename=file.filename or "image", kind=kind,  # type: ignore[arg-type]
        ),
        question=question,
        kind=kind,  # type: ignore[arg-type]
    )


@router.post("/ocr")
async def run_ocr(file: UploadFile = File(...), lang: str = Form(default="eng")) -> dict:
    """Recover text from a scanned page or photographed note."""
    from ...core.registry import registry

    provider = registry.require("ocr", "tesseract")
    data = await read_upload(file)
    source = provider.parse(data, file.filename or "scan", lang=lang)
    return {
        "text": " ".join(p.text for p in source.passages),
        "passages": len(source.passages),
        "note": source.retrieval_note,
    }
