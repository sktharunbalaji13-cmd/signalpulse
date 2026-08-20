"""Tests for URL/title canonicalization (M3-A1). Table-driven and deterministic."""

import pytest
from app.services.canonicalize import canonicalize_url, dedupe_key, normalize_title


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # tracking params stripped
        ("https://news.example/ev/x?utm_source=a&utm_medium=b", "https://news.example/ev/x"),
        # fragment stripped
        ("https://news.example/ev/x#comments", "https://news.example/ev/x"),
        # trailing slash on path removed
        ("https://news.example/ev/x/", "https://news.example/ev/x"),
        # scheme and host lowercased (path stays case-sensitive)
        ("HTTPS://News.Example.com/Ev", "https://news.example.com/Ev"),
        # default port removed
        ("https://news.example:443/x", "https://news.example/x"),
        ("http://news.example:80/x", "http://news.example/x"),
        # non-default port kept
        ("http://news.example:8080/x", "http://news.example:8080/x"),
        # query params sorted deterministically
        ("https://news.example/x?b=2&a=1", "https://news.example/x?a=1&b=2"),
        # root path preserved
        ("https://news.example.com/", "https://news.example.com/"),
        # youtube keeps only the v parameter
        (
            "https://www.youtube.com/watch?v=abc&list=xyz&utm_source=a",
            "https://www.youtube.com/watch?v=abc",
        ),
        # guardian drops the page parameter
        ("https://www.theguardian.com/x?page=all", "https://www.theguardian.com/x"),
        # empty query params dropped
        ("https://news.example/x?a=&b=2", "https://news.example/x?b=2"),
        # duplicate slashes collapsed
        ("https://news.example//a//b", "https://news.example/a/b"),
    ],
)
def test_canonicalize_url(url: str, expected: str) -> None:
    assert canonicalize_url(url) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("How EV Battery Recycling Is Scaling", "how ev battery recycling is scaling"),
        ("  Title   With   Spaces  ", "title with spaces"),
        ("Punctuation: dash — and | pipes!", "punctuation dash and pipes"),
        ("Some headline — The Guardian", "some headline"),
        ("Another story | BBC News", "another story"),
        # NFKC: fullwidth latin folds to ascii
        ("Ｆｕｌｌｗｉｄｔｈ Title", "fullwidth title"),
        ("Keep this title", "keep this title"),
        # unknown suffix is NOT stripped (not a known publisher)
        ("Not a publisher — by our reporter", "not a publisher by our reporter"),
    ],
)
def test_normalize_title(title: str, expected: str) -> None:
    assert normalize_title(title) == expected


def test_normalize_title_preserves_meaningful_suffix() -> None:
    assert normalize_title("Analysis by John Smith") == "analysis by john smith"


def test_bare_publisher_name_is_not_stripped() -> None:
    assert normalize_title("The Guardian") == "the guardian"


def test_dedupe_key_is_stable_and_sensitive() -> None:
    assert dedupe_key("https://news.example/x") == dedupe_key("https://news.example/x")
    assert dedupe_key("https://news.example/x") == dedupe_key("https://news.example/x#frag")
    assert dedupe_key("https://news.example/x") != dedupe_key("https://news.example/y")


def test_url_variants_share_dedupe_key() -> None:
    base = "https://news.example/ev/story"
    variants = [
        "https://news.example/ev/story?utm_source=push&utm_medium=email",
        "https://news.example/ev/story#comments",
        "HTTPS://News.Example/ev/story/",
        "https://news.example:443/ev/story",
    ]
    keys = {dedupe_key(v) for v in variants}
    assert keys == {dedupe_key(base)}


def test_canonicalize_url_is_deterministic() -> None:
    url = "https://news.example/ev/x?utm_source=a&b=2&a=1"
    assert canonicalize_url(url) == canonicalize_url(url)
