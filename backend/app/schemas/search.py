from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class SearchCreate(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    window_hours: int | None = Field(default=None, ge=0, le=8760)

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be empty")
        if len(stripped) > 200:
            raise ValueError("query must be at most 200 characters")
        return stripped

    @field_validator("window_hours")
    @classmethod
    def zero_means_no_limit(cls, value: int | None) -> int | None:
        if value == 0:
            return None
        return value


class SearchCreated(BaseModel):
    search_id: str
    status: str


class SourceStatus(BaseModel):
    name: str
    status: str
    result_count: int | None = None
    latency_ms: int | None = None
    error_type: str | None = None
    error: str | None = None


class SearchStatusResponse(BaseModel):
    search_id: str
    query: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    result_count: int = 0
    sources: list[SourceStatus] = []


class SearchResultItem(BaseModel):
    source_type: str
    source_name: str
    title: str
    description: str | None = None
    url: str
    author: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    language: str | None = None
    is_duplicate: bool = False
    duplicate_group_id: str | None = None


class SearchResultsResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: list[SearchResultItem]


class SearchHistoryItem(BaseModel):
    """M19.1: operational metadata only - raw query text is never served
    through the listing endpoint (ADR 0015)."""

    search_id: str
    status: str
    created_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None
    result_count: int = 0


class SearchHistoryResponse(BaseModel):
    items: list[SearchHistoryItem]


class AdminPurgeResponse(BaseModel):
    """M15.1 admin purge outcome: operational counts only, never content."""

    searches_deleted: int
    results_deleted: int
    source_events_deleted: int
    duplicate_groups_deleted: int
    cutoff_utc: datetime | None = None