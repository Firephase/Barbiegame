"""Request/response schemas for the HTTP API."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .services.citations import STYLES
from .services.export import FORMATS
from .services.modes import MODES


class ControlsIn(BaseModel):
    """User-controlled research parameters (spec §20)."""

    max_sources: int = Field(default=12, ge=1, le=60)
    date_from: date | None = None
    date_to: date | None = None
    source_types: list[str] = Field(default_factory=list)
    academic_only: bool = False
    web_only: bool = False
    open_access_only: bool = False
    include_preprints: bool = True
    language: str | None = None
    region: str | None = None
    domains_include: list[str] = Field(default_factory=list)
    domains_exclude: list[str] = Field(default_factory=list)

    def to_controls(self):
        from .services.retrieval import ResearchControls

        return ResearchControls(**self.model_dump()).clamp()


class ResearchIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    project_id: str | None = None
    mode: str = "quick"
    controls: ControlsIn = Field(default_factory=ControlsIn)
    source_ids: list[str] = Field(default_factory=list)
    use_project_only: bool = False
    force_search: bool = False
    depth: Literal["brief", "standard", "thorough"] = "standard"
    level: Literal["beginner", "student", "researcher", "expert"] = "researcher"
    citation_style: str = "apa"

    @field_validator("mode")
    @classmethod
    def _known_mode(cls, value: str) -> str:
        if value not in MODES:
            raise ValueError(f"Unknown mode '{value}'. Available: {', '.join(MODES)}")
        return value

    @field_validator("citation_style")
    @classmethod
    def _known_style(cls, value: str) -> str:
        if value not in STYLES:
            raise ValueError(f"Unknown citation style '{value}'. Available: {', '.join(STYLES)}")
        return value


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    question: str = ""
    description: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)


class ProjectPatch(BaseModel):
    name: str | None = None
    question: str | None = None
    description: str | None = None
    settings: dict[str, Any] | None = None
    archived: bool | None = None


class ProjectOut(BaseModel):
    id: str
    name: str
    question: str
    description: str
    settings: dict[str, Any]
    archived: bool
    created_at: datetime
    updated_at: datetime
    source_count: int = 0
    message_count: int = 0
    note_count: int = 0
    passage_count: int = 0


class UrlIn(BaseModel):
    url: str = Field(min_length=4, max_length=2000)
    project_id: str | None = None
    question: str | None = None


class VideoIn(BaseModel):
    url: str
    project_id: str | None = None
    question: str | None = None
    languages: list[str] = Field(default_factory=list)


class NoteIn(BaseModel):
    title: str = ""
    body: str = ""
    source_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    pinned: bool = False


class CitationIn(BaseModel):
    source_ids: list[str] = Field(default_factory=list)
    style: str = "apa"
    project_id: str | None = None

    @field_validator("style")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in STYLES:
            raise ValueError(f"Unknown citation style '{value}'.")
        return value


class ExportIn(BaseModel):
    format: str = "md"
    style: str = "apa"
    include_trace: bool = True
    message_id: str | None = None
    project_id: str | None = None
    answer: dict[str, Any] | None = None

    @field_validator("format")
    @classmethod
    def _known_format(cls, value: str) -> str:
        if value not in FORMATS:
            raise ValueError(f"Unknown export format '{value}'. Available: {', '.join(FORMATS)}")
        return value


class ChartIn(BaseModel):
    project_id: str | None = None
    source_id: str | None = None
    rows: list[dict[str, Any]] | None = None
    form: str = "bar"
    x: str | None = None
    y: str | list[str] | None = None
    group: str | None = None
    title: str = ""
    subtitle: str = ""
    x_label: str | None = None
    y_label: str | None = None
    x_unit: str = ""
    y_unit: str = ""
    x_scale: Literal["linear", "log", "symlog"] = "linear"
    y_scale: Literal["linear", "log", "symlog"] = "linear"
    error: str | None = None
    aggregate: Literal["none", "mean", "median", "sum", "count"] = "none"
    mode: Literal["light", "dark"] = "light"
    width: float = Field(default=7.2, ge=2, le=20)
    height: float = Field(default=4.4, ge=2, le=20)


class AnalysisIn(BaseModel):
    project_id: str | None = None
    source_id: str | None = None
    rows: list[dict[str, Any]] | None = None
    operation: Literal["profile", "describe", "compare", "correlate", "regress", "matrix"]
    value_column: str | None = None
    group_column: str | None = None
    x: str | None = None
    y: str | None = None
    columns: list[str] | None = None
    paired: bool = False
    parametric: Literal["auto", "yes", "no"] = "auto"
    alpha: float = Field(default=0.05, gt=0, lt=0.5)
    method: Literal["auto", "pearson", "spearman"] = "auto"


class DiagramIn(BaseModel):
    description: str = Field(min_length=3, max_length=6000)
    kind: str = "flowchart"
    title: str = ""
    project_id: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    presentation_ready: bool = False


class DiagramReviseIn(BaseModel):
    instruction: str = Field(min_length=2, max_length=2000)
    project_id: str | None = None


class ImageQuestionIn(BaseModel):
    question: str | None = None
    kind: str = "auto"
    project_id: str | None = None


class SynthesisIn(BaseModel):
    project_id: str
    source_ids: list[str] = Field(default_factory=list)
    question: str | None = None


class PaperAnalysisIn(BaseModel):
    project_id: str | None = None
    source_id: str
    level: Literal["beginner", "student", "researcher", "expert"] = "researcher"
    question: str | None = None
