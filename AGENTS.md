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

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **trend-researcher** (1697 symbols, 2365 relationships, 15 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/trend-researcher/context` | Codebase overview, check index freshness |
| `gitnexus://repo/trend-researcher/clusters` | All functional areas |
| `gitnexus://repo/trend-researcher/processes` | All execution flows |
| `gitnexus://repo/trend-researcher/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
