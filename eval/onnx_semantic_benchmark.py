# ruff: noqa: E501
"""M11 benchmark: Option A - ONNX int8 local MiniLM as the production semantic
signal, measured against the M10 PyTorch reference and C4 baseline.

Evaluation/benchmark-only; production untouched.

Measured here (local dev hardware; Render numbers are estimates from tier
specs): model size, cold/warm session load, RSS delta, warm single-query
encode, realistic-search encode (1 query + ~23 docs), embedding agreement with
the M10 PyTorch reference (per-text cosine), frozen-corpus SEM1 metrics using
ONNX vectors (nDCG@10/P@10/MRR/probes), and C4 fallback when semantic is off.

Run with the semantic venv:
    <semvenv>/Scripts/python.exe eval/onnx_semantic_benchmark.py
"""

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

MODEL_DIR = Path(
    r"C:\Users\k.tharun balaji\AppData\Local\Temp\opencode\onnx_minilm"
)
REF_JSON = ROOT / "eval" / "data" / "semantic_embeddings.json"
REPORT = ROOT / "eval" / "reports" / "semantic_production_benchmark.md"

import numpy as np  # noqa: E402
import onnxruntime as ort  # noqa: E402
import psutil  # noqa: E402
from transformers import AutoTokenizer  # noqa: E402

from eval import corpus  # noqa: E402
from eval import ranking_eval as r  # noqa: E402
from eval.schema import EvalCorpus, validate_corpus  # noqa: E402

LINES: list[list[str]] = []


def section(title: str) -> None:
    LINES.append([f"## {title}", ""])


def bullet(text: str) -> None:
    LINES.append(["- " + text])


def main() -> int:
    proc = psutil.Process()

    # --- 1. model size ----------------------------------------------------------
    size_mb = (MODEL_DIR / "model_quantized.onnx").stat().st_size / (1024 * 1024)
    section("Option A artifacts (MEASURED, local)")
    bullet(f"int8 ONNX model size: **{size_mb:.1f} MB** (PyTorch fp32 weights ~90 MB)")

    # --- 2. cold load + RAM -------------------------------------------------------
    rss_before = proc.memory_info().rss / (1024 * 1024)
    t0 = time.perf_counter()
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1  # Render free tier: 0.1-0.5 CPU -> single thread
    so = ort.InferenceSession(
        str(MODEL_DIR / "model_quantized.onnx"),
        opts,
        providers=["CPUExecutionProvider"],
    )
    load_s = time.perf_counter() - t0
    rss_after = proc.memory_info().rss / (1024 * 1024)
    rss_delta = rss_after - rss_before
    bullet(f"cold session load: **{load_s:.2f} s** · session RSS delta: "
           f"**{rss_delta:.0f} MB**")
    input_names = [i.name for i in so.get_inputs()]
    bullet(f"ONNX inputs: {input_names}")

    tok = AutoTokenizer.from_pretrained(str(MODEL_DIR))

    def embed_batch(texts: list[str]) -> list[list[float]]:
        enc = tok(texts, padding=True, truncation=True,
                  max_length=256, return_tensors="np")
        feeds = {}
        for name in input_names:
            if name == "input_ids":
                feeds[name] = enc["input_ids"].astype(np.int64)
            elif name == "attention_mask":
                feeds[name] = enc["attention_mask"].astype(np.int64)
            elif name == "token_type_ids":
                feeds[name] = enc.get(
                    "token_type_ids", np.zeros_like(enc["input_ids"])
                ).astype(np.int64)
        out = so.run(None, feeds)[0]
        mask = enc["attention_mask"][:, :, None].astype(np.float32)
        summed = (out * mask).sum(axis=1)
        counts = np.clip(mask.sum(axis=1), 1e-9, None)
        mean = summed / counts
        norm = np.linalg.norm(mean, axis=1, keepdims=True)
        return (mean / np.clip(norm, 1e-12, None)).tolist()

    # --- 3. texts -----------------------------------------------------------------
    ref = json.loads(REF_JSON.read_text(encoding="utf-8"))
    data = validate_corpus(
        EvalCorpus(
            queries=corpus.QUERIES,
            duplicate_groups=corpus.DUPLICATE_GROUPS,
            ambiguous_pairs=corpus.AMBIGUOUS_PAIRS,
            revision=corpus.REVISION,
        )
    )
    doc_texts: dict[str, str] = {}
    q_texts: dict[str, str] = {}
    for q in data.queries:
        q_texts[q.id] = " ".join(q.query.lower().split())
        for item in q.items:
            key = f"{item.title}. {item.description}" if item.description else item.title
            doc_texts[item.id] = key
    unique_docs = sorted(set(doc_texts.values()))
    unique_qs = sorted(set(q_texts.values()))

    # --- 4. warm inference ----------------------------------------------------------
    section("Warm inference (MEASURED, single-threaded int8)")
    embed_batch(unique_qs[:2])  # warm-up
    lat_q = []
    for _ in range(10):
        t = time.perf_counter()
        embed_batch(unique_qs[:1])
        lat_q.append((time.perf_counter() - t) * 1000)
    lat_b = []
    for _ in range(6):
        t = time.perf_counter()
        embed_batch(unique_docs[:23])
        lat_b.append((time.perf_counter() - t) * 1000)
    bullet(f"single query embed: median **{statistics.median(lat_q):.0f} ms** "
           f"(min {min(lat_q):.0f}, max {max(lat_q):.0f})")
    bullet(f"realistic search (~23 docs): median "
           f"**{statistics.median(lat_b):.0f} ms** (min {min(lat_b):.0f}, max {max(lat_b):.0f})")

    # --- 5. encode everything for quality tests --------------------------------------
    t0 = time.perf_counter()
    onnx_doc = dict(zip(doc_texts.values(),
                        embed_batch(list(doc_texts.values())), strict=True))
    onnx_q = dict(zip(q_texts.values(),
                      embed_batch(list(q_texts.values())), strict=True))
    total_enc_s = time.perf_counter() - t0
    bullet(f"full-corpus encode ({len(onnx_doc)} docs + {len(onnx_q)} queries): "
           f"**{total_enc_s:.2f} s**")

    # --- 6. agreement vs PyTorch fp32 --------------------------------------------------
    section("Agreement vs M10 PyTorch fp32 reference (MEASURED)")
    cos_list = []
    for item_id, dtext in doc_texts.items():
        rv = ref["docs"].get(item_id)
        ov = onnx_doc.get(dtext)
        if not rv or not ov:
            continue
        num = sum(a * b for a, b in zip(rv, ov, strict=True))
        na = sum(a * a for a in rv) ** 0.5
        nb = sum(b * b for b in ov) ** 0.5
        cos_list.append(num / (na * nb))
    avg_cos = sum(cos_list) / len(cos_list)
    min_cos = min(cos_list)
    bullet(f"per-text cosine vs reference: avg **{avg_cos:.4f}**, "
           f"min **{min_cos:.4f}** over {len(cos_list)} texts")

    # --- 7. frozen-corpus metrics with ONNX vectors ------------------------------------
    onnx_probe_qs = sorted({" ".join(p["query"].lower().split()) for p in r.probes()})
    onnx_store = {
        "queries": {
            **onnx_q,
            **{qid: onnx_q[q_texts[qid]] for qid in q_texts},
        },
        "docs_by_text": onnx_doc,
        "probe_queries": dict(zip(onnx_probe_qs, embed_batch(onnx_probe_qs), strict=True)),
    }
    orig_cache = r._SEMANTICS_CACHE
    r._SEMANTICS_CACHE = {
        "queries": onnx_store["queries"],
        "probe_queries": onnx_store["probe_queries"],
        "docs_by_text": onnx_store["docs_by_text"],
    }

    means = r._corpus_measurement()["means"]
    probes = r._run_probes()
    sem_row = means["M10_SEM1_semantic_blend"]
    c4_row = means["C4_design_diversity"]
    failed = [
        p["name"] for p in probes["rows"]
        if any(c["passed"] is False for c in p["per_candidate"].values())
    ]

    section("Frozen-corpus SEM1 metrics driven by ONNX int8 vectors (MEASURED)")
    bullet(f"C4 baseline : nDCG@10 {c4_row['ndcg_at_10']:.4f} · "
           f"P@10 {c4_row['precision_at_10']:.4f} · "
           f"MRR {c4_row['reciprocal_rank']:.4f}")
    bullet(f"SEM1-on-int8: nDCG@10 {sem_row['ndcg_at_10']:.4f} · "
           f"P@10 {sem_row['precision_at_10']:.4f} · "
           f"MRR {sem_row['reciprocal_rank']:.4f}")
    bullet("probes with ONNX semantics: "
           + ("ALL PASS" if not failed else "FAILED: " + ", ".join(failed)))

    # --- 8. fallback ---------------------------------------------------------------------
    section("Fallback (MEASURED)")
    sample = data.queries[0].items[:5]
    q0 = " ".join(sample[0].title.lower().split()[:3])
    c4_order = [row["id"] for row in r.rank_combined(
        list(sample), q0, r.CANDIDATES["C4_design_diversity"],
    )]
    sem_off = [row["id"] for row in r.rank_combined(
        list(sample), q0, r.CANDIDATES["M10_SEM1_semantic_blend"], semantics=None,
    )]
    bullet("semantic unavailable -> SEM1 output identical to C4: "
           + ("**True**" if sem_off == c4_order else "**False**"))

    r._SEMANTICS_CACHE = orig_cache

    # --- write ------------------------------------------------------------------------------
    header = [
        "# M11 - Semantic production architecture benchmark (Option A measured)",
        "",
        f"- int8 ONNX model {size_mb:.1f} MB - cold load {load_s:.2f}s - "
        f"session RSS delta {rss_delta:.0f} MB",
        f"- warm encode: query {statistics.median(lat_q):.0f} ms - "
        f"~23-doc batch {statistics.median(lat_b):.0f} ms (single thread)",
        f"- agreement with PyTorch fp32: avg cosine {avg_cos:.4f} (min {min_cos:.4f})",
        "",
    ]
    out = Path(__file__).resolve().parent / "reports"
    out.mkdir(parents=True, exist_ok=True)
    body = "\n".join("\n".join(chunk) for chunk in LINES)
    (out / "semantic_production_benchmark.md").write_text(
        "\n".join(header) + "\n" + body, encoding="utf-8"
    )
    print(header[2])
    print(header[3])
    print(f"wrote {out / 'semantic_production_benchmark.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())