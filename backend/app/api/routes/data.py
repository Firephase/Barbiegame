"""Data analysis and charting (spec §8, §9)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ...core.errors import BadRequest
from ...db import get_session
from ...models import Artifact
from ...schemas import AnalysisIn, ChartIn
from ...services import analysis as stats
from ...services import charts as chart_service
from ..deps import frame_from_request

router = APIRouter(tags=["data"])


@router.post("/analysis")
def analyse_data(body: AnalysisIn, session: Session = Depends(get_session)) -> dict:
    """Profile a dataset or run a statistical test, with its assumptions."""
    frame, name = frame_from_request(session, source_id=body.source_id, rows=body.rows)

    if body.operation == "profile":
        result: dict = {"operation": "profile", "dataset": name, **stats.profile(frame)}
    elif body.operation == "describe":
        result = {
            "operation": "describe",
            "dataset": name,
            "statistics": stats.describe(frame, body.columns),
        }
    elif body.operation == "compare":
        if not (body.value_column and body.group_column):
            raise BadRequest("A comparison needs both 'value_column' and 'group_column'.")
        test = stats.compare_groups(
            frame, body.value_column, body.group_column,
            paired=body.paired, parametric=body.parametric, alpha=body.alpha,
        )
        result = {"operation": "compare", "dataset": name, **test.to_dict()}
    elif body.operation == "correlate":
        if not (body.x and body.y):
            raise BadRequest("A correlation needs both 'x' and 'y'.")
        result = {
            "operation": "correlate",
            "dataset": name,
            **stats.correlate(frame, body.x, body.y, method=body.method).to_dict(),
        }
    elif body.operation == "regress":
        if not (body.x and body.y):
            raise BadRequest("A regression needs both 'x' and 'y'.")
        result = {
            "operation": "regress",
            "dataset": name,
            **stats.regress(frame, body.x, body.y).to_dict(),
        }
    else:
        result = {
            "operation": "matrix",
            "dataset": name,
            **stats.correlation_matrix(frame, body.columns),
        }

    result["reminder"] = (
        "Every number above was computed from the supplied data. Missing values were "
        "excluded, never imputed."
    )
    if body.project_id:
        session.add(
            Artifact(
                project_id=body.project_id, kind="analysis",
                title=f"{body.operation} on {name}", payload=result,
                source_ids=[body.source_id] if body.source_id else [],
            )
        )
        session.flush()
    return result


@router.get("/datasets/{source_id}/columns")
def dataset_columns(source_id: str, session: Session = Depends(get_session)) -> dict:
    """Column names and inferred kinds — what the chart builder offers the user."""
    import pandas as pd

    frame, name = frame_from_request(session, source_id=source_id, rows=None)
    columns = []
    for column in frame.columns:
        series = frame[column]
        columns.append(
            {
                "name": str(column),
                "dtype": str(series.dtype),
                "kind": "numeric" if pd.api.types.is_numeric_dtype(series)
                else "time" if pd.api.types.is_datetime64_any_dtype(series)
                else "categorical",
                "unique": int(series.nunique(dropna=True)),
                "missing": int(series.isna().sum()),
                "sample": [
                    None if pd.isna(v) else (v.item() if hasattr(v, "item") else v)
                    for v in series.dropna().head(4).tolist()
                ],
            }
        )
    return {"dataset": name, "rows": int(len(frame)), "columns": columns}


@router.post("/charts/recommend")
def recommend(body: ChartIn, session: Session = Depends(get_session)) -> dict:
    """Suggest a chart form for these columns, and say why."""
    frame, _ = frame_from_request(session, source_id=body.source_id, rows=body.rows)
    y = body.y if isinstance(body.y, str) else (body.y[0] if body.y else None)
    return chart_service.recommend_form(frame, body.x, y, body.group)


@router.post("/charts")
def create_chart(body: ChartIn, session: Session = Depends(get_session)) -> dict:
    """Build a chart spec from real data. The browser renders it interactively."""
    frame, name = frame_from_request(session, source_id=body.source_id, rows=body.rows)
    spec = chart_service.build_spec(
        frame,
        form=body.form, x=body.x, y=body.y, group=body.group,
        title=body.title, subtitle=body.subtitle,
        x_label=body.x_label, y_label=body.y_label,
        x_unit=body.x_unit, y_unit=body.y_unit,
        x_scale=body.x_scale, y_scale=body.y_scale,
        error=body.error, mode=body.mode, width=body.width, height=body.height,
        aggregate=body.aggregate,
    )
    payload = spec.to_dict()
    payload["dataset"] = name

    artifact_id = None
    if body.project_id:
        artifact = Artifact(
            project_id=body.project_id, kind="chart",
            title=spec.title or f"{spec.form} of {name}", payload=payload,
            source_ids=[body.source_id] if body.source_id else [],
        )
        session.add(artifact)
        session.flush()
        artifact_id = artifact.id
    payload["artifact_id"] = artifact_id
    return payload


@router.post("/charts/render")
def render_chart(
    body: ChartIn,
    fmt: str = Query(default="png", pattern="^(png|svg|pdf)$"),
    dpi: int = Query(default=200, ge=72, le=600),
    session: Session = Depends(get_session),
) -> Response:
    """Render a publication-quality figure for export."""
    frame, _ = frame_from_request(session, source_id=body.source_id, rows=body.rows)
    spec = chart_service.build_spec(
        frame,
        form=body.form, x=body.x, y=body.y, group=body.group,
        title=body.title, subtitle=body.subtitle,
        x_label=body.x_label, y_label=body.y_label,
        x_unit=body.x_unit, y_unit=body.y_unit,
        x_scale=body.x_scale, y_scale=body.y_scale,
        error=body.error, mode=body.mode, width=body.width, height=body.height,
        aggregate=body.aggregate,
    )
    data = chart_service.render(spec, fmt, dpi=dpi)  # type: ignore[arg-type]
    media = {"png": "image/png", "svg": "image/svg+xml", "pdf": "application/pdf"}[fmt]
    slug = (spec.title or spec.form).lower().replace(" ", "-")[:50] or "chart"
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{slug}.{fmt}"'},
    )
