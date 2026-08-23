# ruff: noqa: E501
"""M10: generate deterministic MiniLM embeddings for the frozen corpus v2 AND
every behavioural-probe document/query string, so the evaluation harness can
test the semantic candidate without importing torch. Evaluation-only artifact.

Run with the throwaway semantic venv (has sentence-transformers):
    <semvenv>/Scripts/python.exe eval/generate_semantic_embeddings.py
Writes: eval/data/semantic_embeddings.json
"""

import json
import sys
from pathlib import Path

from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from eval import corpus, ranking_eval  # noqa: E402
from eval.schema import EvalCorpus, validate_corpus  # noqa: E402

MODEL = "all-MiniLM-L6-v2"
OUT = ROOT / "data" / "semantic_embeddings.json"


def norm(text: str) -> str:
    return " ".join(text.lower().split())


def doc_text(title: str, description: str | None) -> str:
    return f"{title}. {description}" if description else title


def main() -> int:
    data = validate_corpus(
        EvalCorpus(
            queries=corpus.QUERIES,
            duplicate_groups=corpus.DUPLICATE_GROUPS,
            ambiguous_pairs=corpus.AMBIGUOUS_PAIRS,
            revision=corpus.REVISION,
        )
    )

    queries: dict[str, str] = {}
    docs: dict[str, str] = {}
    for q in data.queries:
        queries[q.id] = norm(q.query)
        for item in q.items:
            docs[item.id] = doc_text(item.title, item.description)

    # behavioural-probe documents + queries
    probe_queries: dict[str, str] = {}
    seen_probe_texts: set[str] = set()
    for probe in ranking_eval.probes():
        pq = norm(probe["query"])
        probe_queries[pq] = pq
        for item in probe["items"]:
            key = doc_text(item.title, item.description)
            if key not in seen_probe_texts:
                seen_probe_texts.add(key)
                docs[f"probe:{len(seen_probe_texts):03d}:{key[:60]}"] = key

    texts = sorted(set(queries.values()) | set(docs.values()) | set(probe_queries.values()))
    index = {t: i for i, t in enumerate(texts)}

    print(f"model={MODEL} unique texts={len(texts)}")
    model = SentenceTransformer(MODEL)
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

    inv = {i: t for t, i in index.items()}
    payload = {
        "model": MODEL,
        "dim": len(vectors[0]),
        "queries": {qid: [round(float(x), 6) for x in vectors[index[t]]] for qid, t in queries.items()},
        "probe_queries": {
            t: [round(float(x), 6) for x in vectors[index[t]]] for t in probe_queries.values()
        },
        "docs": {
            item_id: [round(float(x), 6) for x in vectors[index[t]]] for item_id, t in docs.items()
        },
        "docs_by_text": {
            t: [round(float(x), 6) for x in vectors[index[t]]] for t in texts
        },
        "texts_index": inv,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())