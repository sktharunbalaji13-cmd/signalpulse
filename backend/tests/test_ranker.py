"""Unit tests for the BM25 ranker (M3-B).

Research artifact preserved under ADR 0007 (BM25 rejected as production
relevance core); these tests pin the experimental implementation only.
"""

from datetime import UTC, datetime

import pytest

from app.services.ranker import (
    BM25Field,
    RankCandidate,
    rank,
    score_candidates,
    tokenize,
)


def _c(title, desc="", stype="news", pub=None, url="https://n.example/x", iid=None):
    return RankCandidate(
        id=iid or title,
        title=title,
        description=desc,
        source_type=stype,
        published_at=pub,
        url=url,
    )


def test_tokenize_lowercases_and_drops_stopwords():
    assert tokenize("Electric Vehicle BATTERY recycling!") == [
        "electric",
        "vehicle",
        "battery",
        "recycling",
    ]
    assert tokenize("the and of a") == []


def test_tokenize_keeps_only_alnum_tokens():
    assert tokenize("EV battery, part 2 — new") == ["ev", "battery", "part", "2", "new"]


def test_bm25_field_idf_is_smoothed_and_never_infinite():
    field = BM25Field(["alpha", "alpha beta", "alpha beta gamma"])
    assert 0.0 < field.idf("alpha")  # in every doc, still finite positive
    assert field.idf("gamma") > field.idf("alpha")
    assert field.idf("missing") > field.idf("gamma")


def test_bm25_more_term_matches_score_higher():
    field = BM25Field(["a b c", "a b"])
    more = field.score_text("a b c", ["a", "b", "c"])
    fewer = field.score_text("a b", ["a", "b", "c"])
    assert more > fewer


def test_bm25_term_frequency_saturates():
    field = BM25Field(["x", "x", "x", "x"])
    once = field.score_text("x", ["x"])
    thrice = field.score_text("x x x", ["x"])
    assert thrice > once
    assert thrice < 3 * once  # k1 saturation, not linear


def test_bm25_length_normalization_prefers_concise_documents():
    field = BM25Field(["alpha filler", "alpha" + " filler" * 10, "alpha filler"])
    concise = field.score_text("alpha" + " filler" * 10, ["alpha", "filler"])
    verbose = field.score_text("alpha" + " filler" * 10 + " padding", ["alpha", "filler"])
    assert concise > verbose


def test_relevance_is_normalized_and_bounded():
    candidates = [
        _c("alpha beta gamma", desc="alpha beta gamma"),
        _c("totally unrelated thing"),
    ]
    scored = score_candidates(candidates, "alpha beta gamma", include_bonuses=False)
    self_match = scored["alpha beta gamma"]["relevance"]
    assert self_match == pytest.approx(1.0, abs=1e-9)
    for entry in scored.values():
        assert 0.0 <= entry["relevance"] <= 1.0


def test_score_components_are_explainable():
    candidates = [
        _c(
            "Electric vehicle battery recycling in Europe",
            "Recycling plants recover lithium.",
            iid="a",
        )
    ]
    full = score_candidates(candidates, "electric vehicle battery recycling", include_bonuses=True)[
        "a"
    ]
    assert {"bm25_title", "bm25_description", "base_relevance"} <= set(full["components"])
    assert full["components"]["exact_phrase_title"] == 1.0
    assert full["relevance"] <= 1.0


def test_bonuses_never_lower_relevance():
    candidates = [
        _c("Battery recycling start-up raises funding", "Hydrometallurgy plant.", iid="a")
    ]
    core = score_candidates(candidates, "battery recycling start-up", include_bonuses=False)["a"]
    full = score_candidates(candidates, "battery recycling start-up", include_bonuses=True)["a"]
    assert full["relevance"] >= core["relevance"]
    assert full["relevance"] <= 1.0


def test_rank_is_deterministic():
    candidates = [
        _c("A story about electric vehicles", "EV description", iid="a"),
        _c("A story about electric vehicles", "EV description", iid="b"),
        _c("Something else entirely", iid="c"),
    ]
    assert rank(candidates, "electric vehicles") == rank(candidates, "electric vehicles")


def test_rank_tie_break_prefers_news_then_newer_then_url():
    pub1 = datetime(2026, 8, 1, tzinfo=UTC)
    pub2 = datetime(2026, 8, 2, tzinfo=UTC)
    candidates = [
        _c(
            "identical title here", "same desc", stype="social",
            pub=pub1, url="https://r.example/z", iid="social",
        ),
        _c(
            "identical title here", "same desc", stype="news",
            pub=pub2, url="https://n.example/z", iid="news2",
        ),
        _c(
            "identical title here", "same desc", stype="news",
            pub=pub1, url="https://n.example/a", iid="news1",
        ),
    ]
    ordered = rank(candidates, "identical title here")
    assert ordered.index("news2") < ordered.index("news1") < ordered.index("social")


def test_rank_places_exact_query_match_first():
    candidates = [
        _c(
            "Electric vehicle battery recycling",
            "Overview of recycling EV batteries.",
            iid="match",
        ),
        _c(
            "Battery recycling start-up raises funding",
            "A company scales a hydrometallurgy plant.",
            iid="decoy",
        ),
        _c(
            "Sales of electric cars hit record",
            "New registrations reached a quarterly record.",
            iid="far",
        ),
    ]
    ordered = rank(candidates, "electric vehicle battery recycling", include_bonuses=False)
    assert ordered[0] == "match"
