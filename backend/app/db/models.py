from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
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
    __table_args__ = (
        UniqueConstraint("search_id", "dedupe_key", name="uq_results_search_dedupe"),
    )

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