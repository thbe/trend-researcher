<!-- GSD:project-start source:PROJECT.md -->
## Project

**Trend Researcher**

A two-stage internal tool that continuously crawls major news, social, and tech sites to surface trending/viral topics, then uses AI to evaluate which of those topics matter for a specific market (starting with retail) and drafts a rough business case for the ones that do.

- **Stage 1 — Ingest (deterministic, zero AI):** Python crawlers periodically pull top-N items from each source using that source's own native ranking signal (NYT homepage, Reddit hot, HN front page, X trending, Instagram, etc.). Items are fuzzy-deduped by title/keyword (rapidfuzz-style) and stored in PostgreSQL as one row per distinct topic. Re-crawls update existing rows (accumulating source references and observation timestamps) rather than inserting duplicates.
- **Stage 2 — Assessment (AI lives only here):** A RAG layer over the Postgres topic store filters topics for relevance to a target market (retail in v1) and, for relevant ones, generates a business case with an importance score and a rough investment-cost estimate.
- **Frontend:** TypeScript + Vuetify control plane to view trends, configure runs, and read the AI-generated business cases.

**Core Value:** Give a single operator 360° situational awareness — early visibility into both **risks** (disasters, geopolitics, wars) and **opportunities** (viral products that need to land in assortment) — fast enough that the business can actually react. By keeping ingest fully deterministic and isolating AI to assessment, the topic store stays trustworthy, cheap to run, and reusable for additional markets later.

### Constraints

- **Stack (locked):** Python (ingest), PostgreSQL (store), TypeScript + Vuetify (frontend), AI tooling such as OpenCode (assessment).
- **AI boundary (locked):** AI runs **only** in Stage 2 assessment. Stage 1 ingest is fully deterministic.
- **Dedup boundary (locked):** Stage 1 dedup uses fuzzy string matching (rapidfuzz-style) only.
- **Operational footprint:** Single-operator internal tool; no HA, no multi-region, no compliance regime in v1.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:STACK.md -->
## Technology Stack

Technology stack not yet documented. Will populate after codebase mapping or first phase.
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
