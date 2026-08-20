from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class SearchStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class SourceEventStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"


class Search(Base):
    __tablename__ = "searches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    query: Mapped[str] = mapped_column(String(200))
    normalized_query: Mapped[str] = mapped_column(String(200), index=True)
    window_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=SearchStatus.RUNNING.value, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Result(Base):
    __tablename__ = "results"
    __table_args__ = (Index("ix_results_search_rank", "search_id", "rank_score"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    search_id: Mapped[str] = mapped_column(ForeignKey("searches.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(20))
    source_name: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rank_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank_components: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rank_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duplicate_group_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    raw: Mapped[dict] = mapped_column(JSON)


class SourceEvent(Base):
    __tablename__ = "source_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    search_id: Mapped[str] = mapped_column(ForeignKey("searches.id"), index=True)
    source_name: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20))
    result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    quota_used: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DuplicateGroup(Base):
    """A duplicate cluster: one canonical result plus its member results.

    Deduplication annotates rather than deletes: every member keeps its own
    ``Result`` row and simply points at this group. ``canonical_result_id`` is
    the representative shown to users; ``duplicate_evidence`` records the
    detection methods (``canonical_url`` / ``normalized_title`` / ``fuzzy_title``)
    so every merge is explainable (PROJECT_SPEC.md §12, design §9).
    """

    __tablename__ = "duplicate_groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    search_id: Mapped[str] = mapped_column(ForeignKey("searches.id"), index=True)
    canonical_result_id: Mapped[str] = mapped_column(ForeignKey("results.id"))
    member_count: Mapped[int] = mapped_column(Integer)
    duplicate_evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)