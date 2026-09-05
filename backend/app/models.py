"""Persistence model for the research workspace (spec §12).

A project owns everything: its questions, the sources it has collected, files,
images, datasets, notes, conversations, diagrams, charts and findings.  Sources
are stored with their full provenance payload so a citation rendered today is
identical to the one rendered in six months.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .core.provenance import new_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Project(Base):
    """A research topic and everything gathered under it."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("prj"))
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    question: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    #: Per-project research controls (spec §20), stored as JSON.
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    sources: Mapped[list["SourceRecord"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", lazy="selectin"
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    notes: Mapped[list["Note"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    events: Mapped[list["TimelineEvent"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class SourceRecord(Base):
    """A source inside a project, with its full provenance payload preserved."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("src"))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40), default="unknown")
    title: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    doi: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    identity_key: Mapped[str] = mapped_column(String(500), index=True)
    #: Full ``Source`` model dump — the single source of truth for citations.
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    quality_tier: Mapped[str | None] = mapped_column(String(40), nullable=True)
    #: Where this came from: search, url, upload, video, manual.
    origin: Mapped[str] = mapped_column(String(30), default="search")
    #: Blob key when the source came from an uploaded file.
    blob_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    media_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passage_count: Mapped[int] = mapped_column(Integer, default=0)
    starred: Mapped[bool] = mapped_column(Boolean, default=False)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped[Project] = relationship(back_populates="sources")

    __table_args__ = (Index("ix_source_project_identity", "project_id", "identity_key"),)


class Message(Base):
    """One turn of a project conversation, with its verified answer attached."""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("msg"))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))          # user | assistant
    mode: Mapped[str] = mapped_column(String(40), default="quick")
    content: Mapped[str] = mapped_column(Text, default="")
    #: Full ``Answer`` dump for assistant turns: claims, sources, trace.
    answer: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    project: Mapped[Project] = relationship(back_populates="messages")


class Artifact(Base):
    """Something the workspace produced: a diagram, chart, analysis or export."""

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("art"))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40))          # diagram | chart | analysis | export | image_analysis
    title: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    blob_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_ids: Mapped[list] = mapped_column(JSON, default=list)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    project: Mapped[Project] = relationship(back_populates="artifacts")


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("note"))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    source_ids: Mapped[list] = mapped_column(JSON, default=list)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    project: Mapped[Project] = relationship(back_populates="notes")


class Finding(Base):
    """A verified claim the user chose to keep — the project's accumulated answers."""

    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("fnd"))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="ai_inference")
    support_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    contested_by: Mapped[list] = mapped_column(JSON, default=list)
    message_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TimelineEvent(Base):
    """The project's research timeline (spec §12)."""

    __tablename__ = "timeline"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40))
    summary: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    project: Mapped[Project] = relationship(back_populates="events")
