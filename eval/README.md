# SignalPulse evaluation harness (M3-A0)

An offline, deterministic corpus and metrics harness for retrieval
intelligence. It exists so M3-A (dedup), M3-B (relevance), M3-C (freshness),
M3-D (ranking) can be measured against an objective baseline — never against
vibes or hand-picked examples.

## Run

From the repository root:

```powershell
python -m eval
```

Writes machine-readable output to `eval/reports/latest.json` (gitignored —
it is reproducible from the corpus, so committing it would only add churn) and
prints a human-readable summary.

The harness is deterministic: repeated runs produce byte-identical output
(no clock, no randomness, fixed timestamps).

## Requirements

- Python 3.11+, `pydantic` (available in the backend virtualenv).
- No internet, no API keys, no LLM, no embeddings — ever.

## Corpus

`eval/corpus.py` defines 15 queries with ~20 fixed synthetic items each
(~300 items total). Every item is fictional and uses `.example` domains; no
real-world events, outlets, or people are being claimed. Items are authored as
Python data structures (not JSON) for maintainability, then validated against
the Pydantic schema in `eval/schema.py`.

The corpus deliberately includes: highly/marginally/irrelevant results, exact
duplicate URLs, URL variants (tracking params, fragments), cross-outlet wire
stories, mobile/AMP variants, exact-title duplicates, paraphrased titles,
publisher boilerplate suffixes, generic-title decoys ("Update"), unrelated
articles with similar wording, Reddit discussion posts, social posts linking to
news articles, Wikipedia reference results, items missing `published_at`, items
with trustworthy timestamps, old-but-relevant reference material, and
recent-but-weakly-relevant results.

## Labeling rules

### Relevance (0 / 1 / 2)

- **2 — highly relevant**: directly answers the query; the item's core subject
  is the query's subject.
- **1 — partially relevant**: related but not central (background, adjacent
  topic, one aspect, or a community discussion of the topic).
- **0 — irrelevant**: unrelated to the query despite possibly sharing a keyword.

### Duplicate clusters and ambiguous pairs

Gold duplicate data has two parts:

1. **`DUPLICATE_GROUPS`** — clusters, one per underlying story, listing all
   item ids that describe the same page/story and should be merged. A single
   cluster can demonstrate several relationship kinds at once (an exact-URL
   pair, a cross-outlet wire copy, and a paraphrased version all point at the
   same story).

   The relationship kinds the corpus contains:

   | kind | how it appears in a cluster |
   |---|---|
   | `exact_url` | two members with the identical URL string |
   | `url_variant` | members whose URLs differ only by tracking params / fragment |
   | `mobile_amp_variant` | an `amp.`/`m.` subdomain edition of the same page |
   | `cross_outlet` | members with different `source_name` (Guardian vs Global Wire) |
   | `exact_title` | identical normalized title, different URLs |
   | `paraphrase` | rephrased title, same story |
   | `boilerplate_suffix` | title differs only by a ` — The Guardian`-style suffix |

2. **`AMBIGUOUS_PAIRS`** — pairs that genuinely require judgment, mostly
   cross-type (a social discussion/link post vs the news article it discusses).
   These are neither asserted true duplicates nor asserted non-duplicates, and
   are **excluded** from dedup precision/recall/F1.

- **True duplicates**: pairs inside a non-ambiguous cluster.
- **Non-duplicates**: every other same-query pair (including generic-title
  "Update" decoys and unrelated similar-wording items — deliberately absent
  from clusters).
- **Ambiguous cases**: the pairs in `AMBIGUOUS_PAIRS`.

## Metrics

Ranking (graded relevance 0/1/2):
- **Precision@5 / Precision@10** — fraction of top-k items that are relevant (rel ≥ 1).
- **MRR** — mean reciprocal rank of the first relevant item.
- **nDCG@10** — graded gain `2^rel − 1`, log2 discount (TREC convention).

Deduplication (over non-ambiguous pairs): **precision, recall, F1** —
`dedup_metrics()` accepts predicted pairs from a future M3-A implementation.

Freshness: `check_freshness()` enforces the M3-C invariants
(monotonic with age, no fabricated timestamp, `retrieved_at` never substitutes,
future timestamps clamped, per-source-type behaviour).

## Baseline

`eval/baseline.py` is a **naive lexical term-count ordering** (title ×3,
description ×1, deterministic tie-break). It is a reference to beat, **not** the
production ranker. The report prints its P@5/P@10/MRR/nDCG@10.

## Targets (targets, not guarantees)

- dedup precision ≥ 0.90 and recall ≥ 0.90
- nDCG@10 ≥ 0.75

These are reported only when actually measured. M3-A0 measures the baseline
ranking and reports dedup/freshness as pending.
