from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SourceResult(BaseModel):
    """Canonical result contract every source adapter must produce.

    Provenance rule: ``raw`` preserves the untouched original API payload so
    every field is auditable against the source response (PROJECT_SPEC.md §16).
    """

    source_type: str
    source_name: str
    title: str
    description: str | None = None
    url: str
    author: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime
    language: str | None = None
    raw: dict[str, Any]


class SearchParams(BaseModel):
    """Small, source-agnostic search options passed through the interface."""

    limit: int = 10
    window_hours: int | None = None


class SourceError(Exception):
    """Raised when a source fails to fetch or parse results.

    ``kind`` maps to the source event status vocabulary:
    "failed" | "timeout" | "rate_limited".
    """

    def __init__(self, message: str, kind: str = "failed") -> None:
        super().__init__(message)
        self.kind = kind


class BaseSourceAdapter(ABC):
    """Contract every external source implements.

    The rest of the application must never depend on a specific source's
    response format — only on this interface and the canonical SourceResult.
    """

    source_type: str
    source_name: str

    @abstractmethod
    async def search(self, query: str, params: SearchParams | None = None) -> list[SourceResult]:
        """Fetch and normalize results for ``query``."""
        raise NotImplementedError