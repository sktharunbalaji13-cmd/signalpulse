"""Deterministic URL and title canonicalization for deduplication (M3-A1).

Canonicalization is the first stage of deduplication. It maps URLs and titles
that point at the same underlying page/story to a stable, comparable form:

* :func:`canonicalize_url` — lowercases scheme/host, drops the fragment, default
  ports, tracking parameters, empty parameters, and trailing slashes, then
  applies a small set of host-specific rules (YouTube keeps only ``v``; Guardian
  drops ``page``).
* :func:`normalize_title` — NFKC-normalizes, lowercases, strips a trailing
  publisher boilerplate suffix, and collapses punctuation/whitespace.
* :func:`dedupe_key` — ``sha256(canonicalize_url(url))``, the stable key stored
  in the ``results.dedupe_key`` column (PROJECT_SPEC.md §12 / §17).

Everything is pure and deterministic: same input -> same output, always.
"""

from __future__ import annotations

import re
import unicodedata
from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_DEFAULT_PORTS = {"http": "80", "https": "443"}

_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "gclsrc",
    "dclid",
    "ref",
    "referrer",
    "source",
    "spm",
    "mtm_source",
    "mtm_medium",
    "mtm_campaign",
    "mtm_content",
    "igshid",
    "mc_cid",
    "mc_eid",
    "yclid",
    "_ga",
    "gbraid",
    "wbraid",
}

# Known publisher names stripped as a trailing boilerplate suffix from titles.
_PUBLISHERS = {
    "the guardian",
    "guardian",
    "bbc",
    "bbc news",
    "reuters",
    "cnn",
    "the new york times",
    "washington post",
    "bloomberg",
    "the verge",
    "arstechnica",
    "global wire",
    "ap news",
    "associated press",
}

# A trailing " - publisher" / " | publisher" / " — publisher" style suffix.
_SUFFIX_RE = re.compile(r"\s*(?:[-|—–])\s*([a-z0-9][a-z0-9 .,&'()]{0,60})$")


def _strip_publisher_suffix(text: str) -> str:
    while True:
        match = _SUFFIX_RE.search(text)
        if match and match.group(1).strip() in _PUBLISHERS:
            text = text[: match.start()].rstrip()
        else:
            return text


def normalize_title(title: str) -> str:
    """Normalize a title for exact-equality comparison (M3-A Stage 1)."""
    text = unicodedata.normalize("NFKC", title).strip().lower()
    text = _strip_publisher_suffix(text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _split_host_port(netloc: str) -> tuple[str, str]:
    if "@" in netloc:
        netloc = netloc.rsplit("@", 1)[1]
    if ":" in netloc:
        host, port = netloc.rsplit(":", 1)
        if port.isdigit():
            return host, port
    return netloc, ""


def _normalize_path(path: str) -> str:
    if not path:
        return "/"
    path = re.sub(r"/{2,}", "/", path)
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path


def _canonicalize_query(query: str) -> str:
    params = parse_qsl(query, keep_blank_values=False)
    params = [(k, v) for k, v in params if k.lower() not in _TRACKING_PARAMS]
    params.sort()
    return urlencode(params)


def _apply_host_rules(host: str, path: str, query: str) -> tuple[str, str]:
    if host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com"):
        keep = [(k, v) for k, v in parse_qsl(query, keep_blank_values=False) if k == "v"]
        keep.sort()
        return urlencode(keep), path
    if host == "theguardian.com" or host.endswith(".theguardian.com"):
        keep = [(k, v) for k, v in parse_qsl(query, keep_blank_values=False) if k != "page"]
        keep.sort()
        return urlencode(keep), path
    return query, path


def canonicalize_url(url: str) -> str:
    """Return a stable, comparable form of ``url`` (M3-A Stage 0)."""
    url = url.strip()
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        return re.sub(r"#.*$", "", url).lower()

    netloc = parts.netloc.lower()
    host, port = _split_host_port(netloc)
    if _DEFAULT_PORTS.get(scheme) == port:
        port = ""
    netloc = host if not port else f"{host}:{port}"

    path = _normalize_path(parts.path)
    query = _canonicalize_query(parts.query)
    query, path = _apply_host_rules(host, path, query)
    return urlunsplit((scheme, netloc, path, query, ""))


def dedupe_key(url: str) -> str:
    """Return the SHA-256 hex digest of ``canonicalize_url(url)``."""
    return sha256(canonicalize_url(url).encode("utf-8")).hexdigest()
