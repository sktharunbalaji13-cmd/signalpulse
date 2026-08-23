"""M11.1 semantic relevance stage (ADR 0012): ONNX-int8 MiniLM, failure-isolated.

Loads the quantized MiniLM ONNX model + tokenizer once (lazy, lock-guarded) and
exposes two entry points used by the search pipeline:

- ``embed_texts(texts)``: batched document embeddings (fresh canonical texts).
- ``embed_query(query)``: LRU-cached single query embedding.

Every public function returns ``None`` on any failure instead of raising — the
caller degrades to pure C4 and records the outcome. No per-search term
statistics and no external services are involved; inference is local ONNX int8
(deterministic on CPU).

The model/tokenizer ship under ``backend/models/minilm-int8/`` so deployments
are self-contained (no hub download at boot).
"""

from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.core.config import settings

_MODEL_DIR = Path(__file__).resolve().parents[2] / "models" / "minilm-int8"

_lock = threading.Lock()
_session = None
_tokenizer = None
_load_failed = False

_QUERY_CACHE_SIZE = 256


class SemanticUnavailable(Exception):
    """Raised internally when the semantic stage cannot run."""


def _load() -> tuple:
    """Load ORT session + tokenizer once; raises SemanticUnavailable on failure."""
    global _session, _tokenizer, _load_failed
    with _lock:
        if _session is not None:
            return _session, _tokenizer
        if _load_failed:
            raise SemanticUnavailable("semantic model previously failed to load")
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer

            model_path = Path(settings.semantic_model_dir)
            if not model_path.is_absolute():
                model_path = _MODEL_DIR
            onnx_path = model_path / "model_quantized.onnx"
            tok_path = model_path / "tokenizer.json"
            if not onnx_path.exists() or not tok_path.exists():
                raise FileNotFoundError(f"semantic model files missing under {model_path}")

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1  # free-tier CPU headroom
            _session = ort.InferenceSession(str(onnx_path), opts,
                                            providers=["CPUExecutionProvider"])
            tokenizer = Tokenizer.from_file(str(tok_path))
            tokenizer.enable_truncation(max_length=256)
            tokenizer.no_padding()
            _tokenizer = tokenizer
        except Exception as exc:  # noqa: BLE001 - stage must never crash the job
            _load_failed = True
            raise SemanticUnavailable(f"semantic load failed: {exc}") from exc
    return _session, _tokenizer


def reset_state() -> None:
    """Reset cached load state (tests only)."""
    global _session, _tokenizer, _load_failed
    with _lock:
        _session = None
        _tokenizer = None
        _load_failed = False
        _embed_query_cached.cache_clear()


def is_loaded() -> bool:
    return _session is not None


def available() -> bool:
    """True when enabled AND the model can be loaded right now (cached verdict)."""
    if not settings.semantic_enabled or _load_failed:
        return False
    try:
        _load()
    except SemanticUnavailable:
        return False
    return True


def _mean_pool_normalize(logits: np.ndarray, attention_mask: np.ndarray) -> list[list[float]]:
    mask = attention_mask[:, :, None].astype(np.float32)
    summed = (logits * mask).sum(axis=1)
    counts = np.clip(mask.sum(axis=1), 1e-9, None)
    mean = summed / counts
    norms = np.linalg.norm(mean, axis=1, keepdims=True)
    return (mean / np.clip(norms, 1e-12, None)).tolist()


def embed_texts(texts: list[str]) -> dict[str, list[float]] | None:
    """Batched document embeddings keyed by input text. None on any failure."""
    if not texts:
        return {}
    try:
        session, tokenizer = _load()
        encodings = tokenizer.encode_batch(texts)
        ids = [e.ids for e in encodings]
        mask = [e.attention_mask for e in encodings]
        max_len = max(len(seq) for seq in ids)
        pad_to = ((max_len + 7) // 8) * 8
        input_ids = np.zeros((len(ids), pad_to), dtype=np.int64)
        attention = np.zeros((len(ids), pad_to), dtype=np.int64)
        for i, (seq, m) in enumerate(zip(ids, mask, strict=True)):
            input_ids[i, : len(seq)] = seq
            attention[i, : len(m)] = m
        logits = session.run(
            None,
            {"input_ids": input_ids, "attention_mask": attention,
             "token_type_ids": np.zeros_like(input_ids)},
        )[0]
        vectors = _mean_pool_normalize(logits, attention)
        return {text: vec for text, vec in zip(texts, vectors, strict=True)}
    except Exception:  # noqa: BLE001 - caller degrades to C4
        return None


@lru_cache(maxsize=_QUERY_CACHE_SIZE)
def _embed_query_cached(normalized_query: str) -> tuple[float, ...] | None:
    session, tokenizer = _load()
    encoding = tokenizer.encode(normalized_query)
    ids = np.array([encoding.ids], dtype=np.int64)
    mask = np.array([encoding.attention_mask], dtype=np.int64)
    logits = session.run(
        None,
        {"input_ids": ids, "attention_mask": mask,
         "token_type_ids": np.zeros_like(ids)},
    )[0]
    vec = _mean_pool_normalize(logits, mask)[0]
    return tuple(float(x) for x in vec)


def embed_query(query: str) -> tuple[float, ...] | None:
    """LRU-cached query embedding. None on any failure."""
    normalized = " ".join(query.lower().split())
    if not normalized:
        return None
    try:
        return _embed_query_cached(normalized)
    except Exception:  # noqa: BLE001 - caller degrades to C4
        return None


def cosine(a: list[float] | tuple[float, ...], b: list[float] | tuple[float, ...]) -> float | None:
    try:
        num = sum(x * y for x, y in zip(a, b, strict=False))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(y * y for y in b) ** 0.5
        return num / (na * nb) if na and nb else 0.0
    except Exception:  # noqa: BLE001
        return None