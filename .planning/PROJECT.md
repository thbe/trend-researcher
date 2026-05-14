# Trend Researcher

## What This Is

A two-stage internal tool that continuously crawls major news, social, and tech sites to surface trending/viral topics, then uses AI to evaluate which of those topics matter for a specific market (starting with retail) and drafts a rough business case for the ones that do.

- **Stage 1 — Ingest (deterministic, zero AI):** Python crawlers periodically pull top-N items from each source using that source's own native ranking signal (NYT homepage, Reddit hot, HN front page, X trending, Instagram, etc.). Items are fuzzy-deduped by title/keyword (rapidfuzz-style) and stored in PostgreSQL as one row per distinct topic. Re-crawls update existing rows (accumulating source references and observation timestamps) rather than inserting duplicates.
- **Stage 2 — Assessment (AI lives only here):** A RAG layer over the Postgres topic store filters topics for relevance to a target market (retail in v1) and, for relevant ones, generates a business case with an importance score and a rough investment-cost estimate.
- **Frontend:** TypeScript + Vuetify control plane to view trends, configure runs, and read the AI-generated business cases.

## Core Value

Give a single operator 360° situational awareness — early visibility into both **risks** (disasters, geopolitics, wars) and **opportunities** (viral products that need to land in assortment) — fast enough that the business can actually react. By keeping ingest fully deterministic and isolating AI to assessment, the topic store stays trustworthy, cheap to run, and reusable for additional markets later.

## Requirements

> Detailed REQ-IDs live in `.planning/REQUIREMENTS.md`. The list below captures intent only.

### Validated for v1
- Periodic Python ingest from a configurable set of sources, top-N per source (default N = 100, tunable per-source).
- Each source contributes its own native trending/hot/viral ranking; cross-source signals are intentionally **not** normalized.
- Fuzzy title/keyword dedup at ingest (rapidfuzz-style, no embeddings, no LLM).
- One row per distinct topic in PostgreSQL with: title, brief description, source references (multi), first/last seen timestamps, observation count, raw metadata.
- Re-crawls UPDATE existing rows; breadth (cross-source count) and longevity (days observed) emerge as importance signals.
- TypeScript + Vuetify frontend to browse topics, configure crawl runs, and read business cases.
- AI assessment layer (RAG over Postgres) that:
  - filters topics for retail-market relevance,
  - rejects irrelevant topics,
  - generates a business case (importance score + rough investment cost) for the rest.
- Architecture stays clean enough to externalize later (clear ingest/store/assessment/UI seams), but no externalization work in v1.

### Active (under discussion)
- Concrete crawl interval(s) and per-source overrides — to be locked in `REQUIREMENTS.md`.
- Initial source list and authentication model per source (public scraping vs API tokens).
- Storage shape for raw vs derived metadata (single JSONB blob vs typed columns).
- Where the AI assessment runs (local OpenCode-style runner vs hosted API) and which model.
- Business-case schema (fields, scoring rubric, cost-estimate format).

### Explicitly Out of Scope (v1 PoC)
- Multi-tenancy.
- Authentication / authorization (internal-only PoC).
- Embeddings, pgvector, or vector clustering **at ingest** (the Stage 2 RAG layer may use embeddings; Stage 1 dedup must not).
- LLM-based deduplication.
- Multi-market support beyond the seed market (retail).
- Normalized cross-source importance scores — each source's native ranking is sufficient for v1.
- Public-facing UI, SSO, billing, audit logs, SLA work.

## Context

- **Audience:** Internal exploration / proof-of-concept. One operator-class user.
- **Reference architecture intent:** Externalizable later — keep ingest, store, assessment, and UI as separable units with clean contracts.
- **Operating mode:** Long-running periodic ingest + on-demand assessment runs against the accumulated store.

## Constraints

- **Stack (locked):** Python (ingest), PostgreSQL (store), TypeScript + Vuetify (frontend), AI tooling such as OpenCode (assessment).
- **AI boundary (locked):** AI runs **only** in Stage 2 assessment. Stage 1 ingest is fully deterministic.
- **Dedup boundary (locked):** Stage 1 dedup uses fuzzy string matching (rapidfuzz-style) only.
- **Operational footprint:** Single-operator internal tool; no HA, no multi-region, no compliance regime in v1.

## Key Decisions

- **Two-stage split (ingest vs assessment).** Keeps the topic store deterministic, trustworthy, and reusable across future markets; isolates AI cost and non-determinism to the layer where it adds value.
- **Native per-source ranking, no normalization.** Each source's hot/trending/viral list is taken as-is. Cross-source incomparability is accepted; breadth (how many sources surfaced a topic) and longevity (how many days it persisted) become the emergent importance signals — for free, with no scoring model to maintain.
- **Top-N per source, default 100, tunable upward.** Bounds ingest volume, lets niche markets widen the funnel (e.g., N=200) without re-architecting.
- **Update-on-recrawl, not insert.** A topic is one row; re-observations accumulate source refs and timestamps. This is what makes breadth and longevity computable.
- **Fuzzy dedup only at ingest.** rapidfuzz-style title/keyword matching. Embeddings and LLM dedup are explicitly deferred — they add cost and non-determinism to a layer that does not need them.
- **Retail as seed market, single-market in v1.** Avoids over-generalizing the assessment prompt before the first market proves the loop works.
- **Internal PoC, no auth/multi-tenancy in v1.** But seams stay clean so externalization is a future feature, not a rewrite.

## Evolution

- _2026-05-14_ — Project scoped via interactive `/gsd-new-project`. Two-stage architecture, deterministic ingest with native per-source ranking, retail as seed market, and the explicit out-of-scope list (auth, multi-tenancy, embeddings/LLM at ingest, multi-market) all locked. PoC success defined as: after 1–2 months runtime, ≥2 of 5 manually reviewed business cases feel genuinely actionable for retail.

---
_Last updated: 2026-05-14_
