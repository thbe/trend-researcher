# Walking Skeleton — Trend Researcher

> The Walking Skeleton is the smallest end-to-end slice that demonstrates the architectural shape works. It's not the MVP — it's the proof that the wiring is sound. The MVP grows by replacing skeleton parts with real ones, not by re-architecting.

## What the skeleton proves

After Phase 1, `docker compose run --rm crawler run-once --top-n 30` walks the entire architecture in a single invocation:

```
HackerNews API
      │  (httpx async GET)
      ▼
HackerNewsSource (adapter, conforms to SourcePort)
      │  list[RawItem]
      ▼
run_once orchestrator (app)
      │  (per item: dedup_key → find_candidates → is_duplicate?)
      ├──── domain.dedup (rapidfuzz)
      │  decision: insert or update
      ▼
SqlAlchemyTopicRepository (adapter, conforms to TopicRepositoryPort)
      │  (async session via asyncpg)
      ▼
Postgres 16 (topics + topic_sources via Alembic migration 0001)
```

Every architectural seam from the locked design (b3) is exercised:

| Seam                         | How the skeleton exercises it                                                                 |
| ---------------------------- | --------------------------------------------------------------------------------------------- |
| Multi-service monorepo       | `services/crawler` runs in its own container, imports `packages/core` as a workspace dep      |
| Ports & adapters per service | `crawler.domain` (pure) + `crawler.ports` (Protocols) + `crawler.adapters` (HN, SA repo)      |
| One-shot job (no scheduler)  | Container `CMD ["run-once"]`; process exits 0 after one crawl                                 |
| Single Alembic tree in core  | Only `packages/core/alembic/` exists — crawler service consumes the schema, doesn't own it    |
| Deterministic ingest (no AI) | `grep` confirms zero LLM imports under `services/crawler/` and `packages/core/`               |
| Update-on-recrawl semantics  | Second `run-once` invocation bumps `observation_count` and `last_seen_at` instead of dup-rows |

## What the skeleton deliberately leaves out

The walking skeleton is a one-legged stick figure. The following are **intentional voids** to be filled by later phases — they are NOT bugs:

- **No scheduler.** External trigger only (Phase 3 wires cron-in-container or system cron).
- **Single source.** Only HackerNews works. Reddit/NYT/Google News land in Phase 2 by adding more `SourcePort` implementations to `build_sources()`.
- **Recent-window candidate scan.** `find_candidates` returns last-50-by-recency. Phase 2 (or later, on demand) can add a Postgres trigram index or full-text search if the recency window misses dedup matches.
- **No API service.** `services/api/` is scaffold only. Phase 4 builds the read API that the UI will consume.
- **No assessor / no AI.** `services/assessor/` is scaffold only. Phase 6 introduces the `LLMPort` and the first cloud + local adapters. The walking skeleton enforces the "no AI in ingest" invariant by structure, not by promise.
- **No web frontend.** `web/` is just `.gitkeep` + README. Phase 4 stands up the Vuetify shell.
- **Cross-source dedup-within-one-run is "skip after first".** If HN and Reddit both surface the same story in the same crawl, only the first will bump observation_count. This is documented in the orchestrator (`01-05-T02`) as a Phase 1 simplification — Phase 2 (when multi-source goes live) decides whether to refine to "merge all observations from one run".

## Why this shape

The skeleton was sized to satisfy three constraints simultaneously:

1. **It must run end-to-end.** A "skeleton" that needs Postgres, but no actual crawler, would not prove the wiring. The HN crawler is small enough to land in one phase but real enough to write 30 actual rows from the actual internet.
2. **It must enforce the locked architectural invariants by code, not by hope.** ARC-001 ("no AI in ingest") and ARC-003 ("ports & adapters layout") are checked by `grep` in the verification block of every plan — the layout is the contract.
3. **Each subsequent phase replaces ONE part.** Phase 2 adds sources (one new file per source). Phase 3 adds scheduling (one new piece of glue, no code changes inside the crawler). Phase 6 adds AI behind a port (the assessor service grows, the crawler is untouched). The skeleton is built so that no future phase requires re-doing earlier work.

## Operator smoke test (the "is it walking?" check)

```bash
cp .env.example .env
docker compose up -d postgres
export DATABASE_URL=postgresql+asyncpg://trend:trend@localhost:5432/trend_researcher
(cd packages/core && uv run alembic upgrade head)
docker compose build crawler
docker compose run --rm crawler run-once --top-n 30
docker compose exec postgres psql -U trend -d trend_researcher \
  -c "SELECT count(*) AS topics, max(observation_count) AS max_obs FROM topics;"
docker compose run --rm crawler run-once --top-n 30
docker compose exec postgres psql -U trend -d trend_researcher \
  -c "SELECT count(*) AS topics, max(observation_count) AS max_obs FROM topics;"
```

After the second `run-once`:
- `topics` count should NOT roughly double (dedup is working).
- `max_obs` should be `>= 2` (update_existing fired).

If both conditions hold, the skeleton is walking. Phase 2 can begin.
