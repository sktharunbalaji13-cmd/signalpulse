"""M7.1 query-intake normalization tests.

``normalize_query`` defines the intake contract (lowercase, whitespace
collapsed); the pipeline must hand that exact string to source adapters while
the original (stripped) query stays on the Search row for display and history.
"""

from datetime import UTC, datetime

import pytest

from app.api.routes.searches import normalize_query
from app.sources.registry import registry


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Artificial Intelligence", "artificial intelligence"),
        ("  artificial   intelligence  ", "artificial intelligence"),
        ("AI\tand\nethics", "ai and ethics"),
        ("   ", ""),
        ("", ""),
        ("quantum!", "quantum!"),  # punctuation is preserved by design
        ("MiXeD CaSe   QuErY", "mixed case query"),
    ],
)
def test_normalize_query_edge_cases(raw: str, expected: str):
    assert normalize_query(raw) == expected


class QueryCaptureAdapter:
    """Fake source that records the query string it was asked for."""

    source_type = "news"
    source_name = "Capture"

    def __init__(self) -> None:
        self.seen_queries: list[str] = []

    async def search(self, query: str, params=None) -> list:
        from app.sources.base import SourceResult

        self.seen_queries.append(query)
        return [
            SourceResult(
                source_type=self.source_type,
                source_name=self.source_name,
                title=f"capture {query}",
                url="https://example.com/capture",
                retrieved_at=datetime.now(UTC),
                raw={},
            )
        ]


def test_adapters_receive_normalized_query(client, session_factory, monkeypatch):
    from app.db.models import Result, Search

    adapter = QueryCaptureAdapter()
    monkeypatch.setattr(registry, "_adapters", {"capture": adapter})

    response = client.post(
        "/api/v1/searches", json={"query": "  Artificial   Intelligence  "}
    )
    assert response.status_code == 202
    search_id = response.json()["search_id"]

    # TestClient runs the background job before the POST returns.
    assert adapter.seen_queries == ["artificial intelligence"]

    with session_factory() as session:
        row = session.get(Search, search_id)
        assert row is not None
        assert row.normalized_query == "artificial intelligence"
        # original (stripped) query preserved for display/history
        assert row.query == "Artificial   Intelligence"
        assert session.query(Result).filter_by(search_id=search_id).count() == 1