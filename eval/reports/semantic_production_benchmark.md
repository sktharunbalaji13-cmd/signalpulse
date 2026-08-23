# M11 - Semantic production architecture benchmark (Option A measured)

- int8 ONNX model 21.9 MB - cold load 0.12s - session RSS delta 35 MB
- warm encode: query 2 ms - ~23-doc batch 94 ms (single thread)
- agreement with PyTorch fp32: avg cosine 0.9904 (min 0.9797)

## Option A artifacts (MEASURED, local)

- int8 ONNX model size: **21.9 MB** (PyTorch fp32 weights ~90 MB)
- cold session load: **0.12 s** · session RSS delta: **35 MB**
- ONNX inputs: ['input_ids', 'attention_mask', 'token_type_ids']
## Warm inference (MEASURED, single-threaded int8)

- single query embed: median **2 ms** (min 2, max 3)
- realistic search (~23 docs): median **94 ms** (min 90, max 97)
- full-corpus encode (350 docs + 16 queries): **2.26 s**
## Agreement vs M10 PyTorch fp32 reference (MEASURED)

- per-text cosine vs reference: avg **0.9904**, min **0.9797** over 365 texts
## Frozen-corpus SEM1 metrics driven by ONNX int8 vectors (MEASURED)

- C4 baseline : nDCG@10 0.7850 · P@10 0.8688 · MRR 0.8750
- SEM1-on-int8: nDCG@10 0.8065 · P@10 0.8750 · MRR 0.9062
- probes with ONNX semantics: ALL PASS
## Fallback (MEASURED)

- semantic unavailable -> SEM1 output identical to C4: **True**