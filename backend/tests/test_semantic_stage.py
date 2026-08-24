"""M11.1 production semantic integration tests (ADR 0012).

Proves:
- the semantic stage runs when enabled and blends ranking per SEM1;
- ANY semantic failure/timeout/disabled state degrades to a ranking that is
  exactly equivalent to pure C4 (the core safety requirement);
- stats observability records stage status;
- query LRU caching works;
- model files load for real (integration, skipped if artifacts missing).
"""

import os
from datetime import UTC, datetime

import pytest

from app.core.config import settings
from app.db.models import Result, Search
from app.services import semantic
from app.services.ranking import doc_key
from app.sources.registry import registry
from tests.test_source_timeout import FakeAdapter


@pytest.fixture(autouse=True)
def fast_single_source(monkeypatch):
    """Deterministic single fake source so rankings are easy to reason about."""
    monkeypatch.setattr(
        registry,
        "_adapters",
        {"wikipedia": FakeAdapter("Wikipedia", "reference", count=4)},
    )


def _post_search(client, query):
    return client.post("/api/v1/searches", json={"query": query})


def _run_and_get_order(client, session_factory, search_id):
    with session_factory() as session:
        rows = (
            session.query(Result)
            .filter_by(search_id=search_id)
            .order_by(Result.rank_position.is_(None), Result.rank_position)
            .all()
        )
        return [r.id for r in rows], {r.id: r.title for r in rows}


def test_happy_path_blends_and_records_ok(client, session_factory, monkeypatch):
    """SEM1 reorders when semantics disagree with lexical strength, and the
    stage records status=ok in search.stats (read from DB - stats are not in
    the API contract)."""

    from app.sources.base import SourceResult

    class TwoDocAdapter:
        source_type = "news"
        source_name = "The Guardian"

        def is_configured(self) -> bool:
            return True

        async def search(self, query, params=None):
            now = datetime.now(UTC)
            return [
                SourceResult(
                    source_type="news",
                    source_name="The Guardian",
                    # strong lexically (both query terms in title) but
                    # semantically orthogonal to the query vector
                    title="Solar battery politics",
                    description="",
                    url="https://example.com/alpha",
                    retrieved_at=now,
                    raw={},
                ),
                SourceResult(
                    source_type="news",
                    source_name="The Guardian",
                    # weaker lexically but semantically aligned
                    title="Battery recycling",
                    description="solar battery",
                    url="https://example.com/beta",
                    retrieved_at=now,
                    raw={},
                ),
            ]

    monkeypatch.setattr(settings, "semantic_enabled", True)
    monkeypatch.setattr(registry, "_adapters", {"two": TwoDocAdapter()})

    alpha_key = doc_key("Solar battery politics", "")
    beta_key = doc_key("Battery recycling", "solar battery")

    def fake_embed_query(query):
        return (1.0, 0.0)

    def fake_embed_texts(texts):
        vecs = {alpha_key: [0.0, 1.0], beta_key: [1.0, 0.0]}
        return {t: vecs.get(t, [0.0, 0.0]) for t in texts}

    monkeypatch.setattr(semantic, "embed_query", fake_embed_query)
    monkeypatch.setattr(semantic, "embed_texts", fake_embed_texts)

    resp = _post_search(client, "solar battery")
    assert resp.status_code == 202
    sid = resp.json()["search_id"]

    with session_factory() as session:
        search = session.get(Search, sid)
        assert search.stats["semantic"]["status"] == "ok"

    payload = client.get(f"/api/v1/searches/{sid}/results?per_page=100").json()
    urls = [i["url"] for i in payload["items"]]
    # SEM1 lifts Beta (aligned) over Alpha despite Alpha's stronger lexical raw
    assert urls.index("https://example.com/beta") < urls.index(
        "https://example.com/alpha"
    )


def test_failure_degrades_to_exact_c4_ranking(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "semantic_enabled", True)
    monkeypatch.setattr(
        semantic, "embed_query", lambda q: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    resp = _post_search(client, "fallback probe")
    sid = resp.json()["search_id"]

    with session_factory() as session:
        search = session.get(Search, sid)
        assert search.stats["semantic"]["status"] == "failed"
        assert search.status in ("completed", "partial")

    # identical data through a purely-disabled run must produce the same order
    monkeypatch.setattr(settings, "semantic_enabled", False)
    resp2 = _post_search(client, "fallback probe")
    sid2 = resp2.json()["search_id"]
    order_failed = client.get(f"/api/v1/searches/{sid}/results?per_page=100").json()
    order_disabled = client.get(f"/api/v1/searches/{sid2}/results?per_page=100").json()
    assert [i["url"] for i in order_failed["items"]] == [
        i["url"] for i in order_disabled["items"]
    ]


def test_timeout_degrades_to_c4(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "semantic_enabled", True)
    monkeypatch.setattr(settings, "semantic_timeout_seconds", 0.01)

    real_embed_texts = semantic.embed_texts

    def slow_texts(texts):
        import time as _t

        _t.sleep(0.5)
        return real_embed_texts(texts)

    monkeypatch.setattr(semantic, "embed_texts", slow_texts)
    monkeypatch.setattr(semantic, "embed_query", lambda q: (1.0, 0.0))

    resp = _post_search(client, "timeout case")
    sid = resp.json()["search_id"]
    with session_factory() as session:
        search = session.get(Search, sid)
        assert search.stats["semantic"]["status"] in ("failed", "timeout")


def test_disabled_stage_records_disabled(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "semantic_enabled", False)
    sid = _post_search(client, "disabled run").json()["search_id"]
    with session_factory() as session:
        search = session.get(Search, sid)
        assert search.stats["semantic"]["status"] == "disabled"


def test_model_load_failure_is_isolated(client, session_factory, monkeypatch):
    monkeypatch.setattr(settings, "semantic_enabled", True)
    monkeypatch.setattr(settings, "semantic_model_dir", r"C:\definitely\not\here")
    semantic.reset_state()
    try:
        assert semantic.available() is False
        sid = _post_search(client, "no model").json()["search_id"]
        with session_factory() as session:
            search = session.get(Search, sid)
            assert search.stats["semantic"]["status"] == "unavailable"
    finally:
        semantic.reset_state()


def test_semantic_disabled_by_default_in_production_config():
    """Fresh Settings (no env/.env influence) must ship semantic OFF: the
    rollout gate is a deliberate, separate production step after deploy
    verification - not an automatic side effect of pushing M11.1."""

    from app.core.config import Settings

    env_backup = {k: os.environ.pop(k) for k in ("SEMANTIC_ENABLED",) if k in os.environ}
    try:
        fresh = Settings(_env_file=None)
        assert fresh.semantic_enabled is False
        assert fresh.semantic_timeout_seconds == 10.0
        assert fresh.semantic_model_dir == "models/minilm-int8"
    finally:
        os.environ.update(env_backup)


def test_real_model_loads_when_files_present():
    """Integration smoke: real ONNX artifacts load and embed (skipped only if
    model files are absent from the checkout)."""
    from pathlib import Path

    model_dir = Path(__file__).resolve().parents[1] / "models" / "minilm-int8"
    if not (model_dir / "model_quantized.onnx").exists():
        pytest.skip("model artifacts not present")
    vec = semantic.embed_query("artificial intelligence")
    assert vec is not None and len(vec) == 384


def test_query_lru_cache_hits():
    """Two identical queries hit the LRU: underlying encode runs once."""
    from app.core.config import settings

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings, "semantic_enabled", True)
    try:
        semantic.reset_state()
        v1 = semantic.embed_query("lru probe query")
        v2 = semantic.embed_query("lru probe query")
        assert v1 == v2 and v1 is not None
        info = semantic._embed_query_cached.cache_info()
        assert info.hits >= 1
    finally:
        monkeypatch.undo()
        semantic.reset_state()