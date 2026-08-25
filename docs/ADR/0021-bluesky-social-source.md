# ADR 0021: Bluesky as the social source — activates the dormant `social` type

- **Status:** Accepted
- **Date:** 2026-08-25
- **Milestone:** M22.4
- **Related:** [ADR 0019](0019-github-code-source.md) (type-gate pattern), [ADR 0017](0017-source-availability-semantics.md), M22.0 audit (Reddit blocked, Mastodon NO-GO, X blocked)

## Context

Reddit — the intended social source — remains externally blocked, Mastodon
was NO-GO'd on search/auth, and X is economically blocked (no viable free
tier, M22.0). Bluesky's public AppView `searchPosts` is the only viable
keyless candidate for the public-social evidence class.

**Scope discipline.** The M22.4 audit found two mid-2026 API changes:
`public.api.bsky.app` returns **403 for search**, and anonymous **`cursor`
pagination is blocked** (first page only). This adapter therefore pins
`api.bsky.app` and is **single-page, first-25 only** — no cursor, no
`until`-walk, no authentication in v1.

**Type decision — reuse the dormant `social` type.** Bluesky is not a new
evidence class; it is the long-missing activation of `social`. The existing
constants already fit a time-critical microblog:
`TYPE_PRIORITY["social"]=1`, `WEIGHTS["social"]=(0.55, 0.30, 0.15)`,
12-hour freshness half-life. The **only** ranking change is a per-source
quality override, **below** Reddit's 0.50:

| Constant | Value | Rationale |
|---|---|---|
| `SOURCE_QUALITY["Bluesky"]` | **0.45** | open microblog, flatter and noisier than Reddit's threaded curation |

Engagement counts (like/repost/reply/quote) are provenance only — **never
ranking inputs** (same discipline as GitHub stars, SO scores).

## Contract mapping

- **title** = post `record.text` (lexicon-capped at 300 chars — the whole post fits)
- **url** = derived `https://bsky.app/profile/{handle}/post/{rkey}` from the
  `at://` post `uri` (canonical, unique per post)
- **author** = public `author.handle` / `displayName` (public pseudonym)
- **published_at** = `record.createdAt` (author-stated time; `indexedAt` is
  index time, not publish time)
- **language** = `record.langs[0]` or None (honest)
- **raw** = `uri`, full `record`, engagement counts, `indexedAt`

## Evaluation (live gate, 2026-08-25, pre-registration)

Ten queries through the real adapter with the production User-Agent:

| Metric | Result |
|---|---|
| Success rate | **10/10** |
| Yield | mean **23.3**/query |
| Latency | p50 **1.75 s**, p95 **2.24 s**, max 2.24 s |
| Over 4.5 s budget | **0/10** |
| Result quality | genuine public-social: official `@postgresql.org` news, developer posts, climate reactions, AI-content chatter; language coverage partial but honest |

**Dedup:** post text rarely contains article URLs (link-card embeds instead);
canonical URL is unique per post. Near-zero cross-source overlap vs
HN/GitHub/news (measured 0 URLs / 100 posts in the audit). Existing exact-URL
dedup suffices; no dedup changes.

Corpus rankings bit-identical by construction (no `social` rows in the frozen
corpus; only a per-source quality constant added), pinned by the full suite.

## Failure semantics

Keyless → always configured (no disabled path needed). HTTP 429 →
`rate_limited`; HTTP 403 → `failed` (covers the pagination/host restriction);
timeout → `timeout`; unexpected → attributable SourceEvent (M22.x fix).

## Consequences

- Seven enabled sources once deployed (+ Reddit dormant): the **social** class
  is finally live.
- Single-page v1 means ≤25 social results per search — an honest structural
  cap, not a workaround.
- Future expansion (cursor via auth, `until`-walk) is gated on a demonstrated
  need and new evidence.