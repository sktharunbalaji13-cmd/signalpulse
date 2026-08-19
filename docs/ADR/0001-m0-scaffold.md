# ADR 0001: M0 engineering scaffold

- **Status:** Accepted
- **Date:** 2026-08-19
- **Related spec:** PROJECT_SPEC.md v0.2 (§11, §31)

## Context

M0 must establish a clean, runnable, testable repository foundation before any
SignalPulse functionality is built. The goal is a vertical "hello world" slice
(backend health endpoint + minimal frontend) with CI, so every later milestone
starts from a green baseline.

## Decision

### Why FastAPI
- Native `async` support is the architectural backbone of SignalPulse: queries
  fan out to multiple external sources in parallel (see PROJECT_SPEC.md §8).
  Flask/Django are sync-first and would fight that design.
- Automatic OpenAPI docs (`/docs`, `/openapi.json`) are free developer UX.
- Pydantic v2 validation is built in and matches the canonical `SourceResult`
  model planned for M1+.

### Why React + Vite + TypeScript
- The MVP is a card/filter/status-polling UI — a component model fits naturally.
- Vite is the fastest scaffold and the de-facto React tooling standard in 2026.
- TypeScript catches contract errors at compile time, which matters once we
  define the API response shapes in M1+.

### Why monorepo
- One repo for backend, frontend, docs, and eval set keeps the whole project
  reviewable in a single place and matches the documented repo layout
  (PROJECT_SPEC.md §30). No shared build tooling is needed yet, so a monorepo
  costs nothing at this stage.

### Why M0 contains no external integrations
- The spec's validated source set (Guardian, GDELT, Reddit, Wikipedia) has its
  own decision gates and rate-limit handling (Appendix A). Adding any of that in
  M0 would couple scaffold work to external API availability, key registration,
  and approval queues (Reddit can take 2–4 weeks). M0 must stay deterministic
  and fully offline-testable.

### Why we are deliberately avoiding Redis, Celery, authentication, and LLM
- PROJECT_SPEC.md §11 and §21 already justify postponing all of these (in-process
  fan-out and a DB-backed 15-min cache are sufficient at MVP scale; LLM is V3).
  Adding them in M0 would be speculative infrastructure with no consumer yet.

## Consequences
- The repository is runnable end-to-end (backend up, frontend up, CI green)
  with zero external dependencies.
- Every future milestone starts from a known-good baseline.
- M0 does not yet demonstrate any SignalPulse-specific functionality; that is
  intentional and explicitly out of scope.
- SQLite is the development database; PostgreSQL is deferred to deployment
  (M4) per PROJECT_SPEC.md §11.