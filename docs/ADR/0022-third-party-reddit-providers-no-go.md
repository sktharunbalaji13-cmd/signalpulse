# ADR 0022: third-party Reddit providers — NO-GO on authorization/provenance grounds

- **Status:** Accepted (NO-GO)
- **Date:** 2026-08-25
- **Milestone:** M22.6
- **Related:** [ADR 0004](0004-reddit-integration.md) (Reddit integration), [ADR 0005](0005-gdelt-gate.md) (gate precedent), [ADR 0017](0017-source-availability-semantics.md), [ADR 0021](0021-bluesky-social-source.md)

## Context

Reddit — the intended social source — has remained dormant since launch
because official API approval was never granted (M17 readiness audit passed;
activation blocked solely on external approval). A third-party provider,
**FetchLayer**, was evaluated as a potential workaround.

**Technical fit was strong.** FetchLayer offers structured REST search over
Reddit posts/comments/subreddits/users with Bearer-key auth, provider-managed
rate limiting, canonical Reddit URLs, and pay-as-you-go pricing (~$3/month at
SignalPulse's ~50 searches/day). On engineering merit alone it would score
well against the adapter contract.

## The decisive problem: authorization and provenance

SignalPulse's provenance chain for every source is explicit:
`source → adapter → SourceResult → evidence → user`. With FetchLayer the
chain becomes:

```
SignalPulse → FetchLayer → unknown retrieval mechanism → Reddit
```

Reddit's current policies (Responsible Builder Policy, updated 2026-06-05;
"Don't break the site") require **approval before accessing Reddit data
through Reddit's API** and explicitly prohibit **scraping without an
authorized agreement**. FetchLayer self-describes as independent and
unaffiliated with Reddit, performs real-time retrieval of public pages
through its own mechanism, and publishes no documentation of an authorized
agreement with Reddit. Its own terms place downstream-use responsibility on
the customer and disclaim blanket reuse rights.

Three distinct questions collapse into the same missing fact:

1. Public accessibility does not imply authorization to scrape.
2. Even an authorized FetchLayer acquisition would not automatically imply
   authorization for **downstream API redistribution** to SignalPulse.
3. Nothing establishes SignalPulse's intended display/indexing use as
   permitted, nor the takedown/retention obligations that would apply.

A successful API response proves the service works; it proves nothing about
permission. Privacy exposure compounds the concern: user-profile endpoints
and per-user data create controller obligations SignalPulse does not need or
want (its privacy model stores no identifiers and harvests no profiles).

## Decision

**NO-GO for all third-party Reddit providers**, regardless of technical
quality:

| Candidate | Verdict |
|---|---|
| Official Reddit API | 🟢 Preferred path if approval is ever granted |
| Devvit | 🔴 NO-GO |
| Direct scraping | 🔴 NO-GO |
| `.json` endpoint workarounds | 🔴 NO-GO |
| FetchLayer / any unofficial mirror or scraper | 🔴 NO-GO — identical gate |

The social evidence class remains covered by Bluesky (ADR 0021).

## Reopen condition

This decision is reopened **only** by documented evidence of an authorized
agreement covering **both** the upstream acquisition (FetchLayer↔Reddit or
equivalent) **and** SignalPulse's intended downstream use. Marketing claims
of lawfulness, free tiers, or working integrations do not satisfy this bar.
Until then Reddit stays dormant — implemented, honestly labeled `disabled`,
and activatable by configuration alone the moment official credentials land.

## Consequences

- The clean portfolio/interview position is preserved: SignalPulse declined a
  technically convenient source because its provenance could not be
  established — evidence-driven judgment applied to sourcing policy, not just
  ranking.
- This record prevents silent re-addition of the same idea under a different
  provider name (the GDELT-gate pattern, ADR 0005).
- No code, configuration, dependencies, or production changes were made; the
  audit itself consumed no API quota and created no account.