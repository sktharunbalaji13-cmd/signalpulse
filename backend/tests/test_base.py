from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.sources.base import SourceResult


def test_source_result_accepts_valid_fields():
    now = datetime.now(UTC)
    result = SourceResult(
        source_type="reference",
        source_name="Wikipedia",
        title="Artificial intelligence",
        description="An intro.",
        url="https://en.wikipedia.org/wiki/Artificial_intelligence",
        author=None,
        published_at=None,
        retrieved_at=now,
        language="en",
        raw={"pageid": 1},
    )

    assert result.source_type == "reference"
    assert result.published_at is None
    assert result.retrieved_at == now
    assert result.raw == {"pageid": 1}


def test_source_result_optional_fields_default_to_none():
    now = datetime.now(UTC)
    result = SourceResult(
        source_type="reference",
        source_name="Wikipedia",
        title="T",
        url="https://en.wikipedia.org/wiki/T",
        retrieved_at=now,
        raw={},
    )

    assert result.description is None
    assert result.author is None
    assert result.published_at is None
    assert result.language is None


@pytest.mark.parametrize(
    "missing",
    ["source_type", "source_name", "title", "url", "retrieved_at", "raw"],
)
def test_source_result_requires_mandatory_fields(missing):
    now = datetime.now(UTC)
    data = {
        "source_type": "reference",
        "source_name": "Wikipedia",
        "title": "T",
        "url": "https://example.org",
        "retrieved_at": now,
        "raw": {},
    }
    del data[missing]

    with pytest.raises(ValidationError):
        SourceResult(**data)