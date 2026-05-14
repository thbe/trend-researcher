# Phase 2 Context: Multi-Source Ingest

## Goal
Onboard the remaining v1 sources behind the source-plugin contract from Phase 1. After this phase, a single `crawler run-once` invocation fans out across **six sources** and every distinct trending story shows up exactly once in `topics`, with one `topic_sources` row per (source, observation).

## Locked Decisions (carried into Phase 2 plans)

### Source set (final, no TBDs)
| # | Source           | Adapter type     | Endpoint                                                                  | Why                                  |
|---|------------------|------------------|---------------------------------------------------------------------------|--------------------------------------|
| 1 | `hackernews`     | JSON (Firebase)  | (already in Phase 1)                                                      | tech leading indicator               |
| 2 | `reddit_all`     | JSON (Reddit)    | `https://www.reddit.com/r/all/hot.json`                                   | broad zeitgeist / virality           |
| 3 | `reddit_business`| JSON (Reddit)    | `https://www.reddit.com/r/business/hot.json`                              | macro / company news                 |
| 4 | `reddit_retail`  | JSON (Reddit)    | `https://www.reddit.com/r/retail/hot.json`                                | direct domain                        |
| 5 | `reddit_bifl`    | JSON (Reddit)    | `https://www.reddit.com/r/BuyItForLife/hot.json` (**user pick**)          | consumer demand for durable products |
| 6 | `nyt_homepage`   | RSS (XML)        | `https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml`               | mainstream agenda                    |
| 7 | `google_news`    | RSS (XML)        | `https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en`                   | aggregated headlines, dedup partner  |

That is **7 sources total** (HN already shipped + 6 new). The roadmap originally said "six v1 sources" — the BIFL pick brings the new-source count to 6, total 7. The Phase 2 success criterion "all six v1 sources" was written before BIFL was on the menu; we will validate against the seven that actually ship and document the discrepancy in the roadmap update.

### Schema decision
**No schema changes in Phase 2.** Phase 1 already shipped `Topic.observation_count` (denormalized counter, bumped per re-observation) and `Topic.last_seen_at` (denormalized timestamp, bumped per re-observation). The repository's `update_existing` already increments both. Cross-source dedup uses the same `find_candidates` + `is_duplicate` path — no new tables, no new columns. (The earlier "row-per-observation vs counter" debate was based on an incorrect read of the model; the schema already matches the desired option.)

### Cross-source dedup
- The Phase 1 dedup primitives (`dedup.dedup_key` + `dedup.is_duplicate`, threshold 85, rapidfuzz `token_set_ratio`) are **source-agnostic** by design.
- A story appearing on NYT and Google News will already collapse to one `topic` row with **two** `topic_sources` rows (different `source_name`, possibly different `url`).
- The `find_candidates` recent-window scan in `SqlAlchemyTopicRepository` is also source-agnostic.
- **Therefore cross-source dedup needs no new code.** It needs a **test** to prove it.

### Native rank preservation
Each source writes its own `native_rank` to its own `topic_sources` row. No cross-source normalization. Phase 1 already enforces this; Phase 2 just inherits.

### Orchestrator behavior
The Phase 1 orchestrator (`crawler.app.orchestrator.run_once_async`) already iterates over `sources: list[SourcePort]` from the composition root. Phase 2 just **registers more adapters in `build_sources()`**. The orchestrator code itself does not change.

### Per-source failure isolation
A single source failing (network error, malformed payload, rate limit) **must not** abort the whole run. The orchestrator's per-source loop must catch + log + continue. (Phase 1 didn't need this because there was only one source.)

### HTTP / politeness
- Reddit JSON requires a non-default `User-Agent` (it returns 429 to default httpx UA). Use `Trend-Researcher/0.1 (internal PoC; +https://github.com/thbe/trend-researcher)`.
- All HTTP timeouts: 10s connect/read, matches HN.
- No retries in v1 (one-shot job; next run picks up what was missed). Document this.

### RSS parsing
- Use `feedparser` (battle-tested, permissive, no async — wrap in `asyncio.to_thread`).
- Skip items without `title` or `link`. Log + count skipped.
- `observed_at` = the wall clock at fetch time (NOT the RSS `pubDate`), matching HN behavior. The RSS `pubDate` goes into `raw_payload` if needed later.

## Test discipline (binding for all Phase 2 plans)
- **TDD where practical**: for every new adapter, domain function, or orchestrator branch, the test is written **before or alongside** the implementation in the same task. No task is "done" until its tests are green.
- **Coverage rule**: every public function / method introduced in Phase 2 has at least one direct unit test. No untested public surface ships.
- **Test types per layer**:
  - `domain/` → pure unit tests, no mocks needed (zero I/O by construction).
  - `adapters/sources/` → unit tests with `httpx.MockTransport` or hand-rolled fakes; no live network in CI/PR runs.
  - `adapters/persistence/` → integration tests gated on `TEST_DATABASE_URL` (skip if absent), matching the Phase 1 pattern.
  - `app/orchestrator.py` → unit tests using `FakeSource` / `FakeRepository` (in-memory), no DB, no HTTP.
- **Live-network E2E** (one source actually hits the internet) is allowed only in plan 02-04 and only as a manually-invoked smoke, not in the default pytest run.
- **Verification gate per plan**: `uv run --package crawler pytest -v` must exit 0 before any plan is marked complete.

## Out of Scope (defer)
- Trigram index on `topics.title` (still recent-window scan; Phase 1 simplification holds).
- Scheduling — still operator-invoked one-shot, scheduler is Phase 3.
- Reddit OAuth — anonymous JSON endpoint is sufficient for top-N polling at single-operator volume.
- A "sources registry" table — `build_sources()` list is fine; `crawl_config` table is Phase 5.
- UI of any kind.
- AI / assessment of any kind (ARC-001 hard rule).

## References (live code, not aspirational)
- `services/crawler/src/crawler/ports/source_port.py` — protocol new adapters implement
- `services/crawler/src/crawler/adapters/sources/hackernews.py` — reference adapter
- `services/crawler/src/crawler/app/composition.py:23` — `build_sources()` registration point
- `services/crawler/src/crawler/app/orchestrator.py` — `run_once_async` loop
- `services/crawler/src/crawler/domain/dedup.py` — source-agnostic dedup
- `packages/core/src/core/models.py` — schema (no changes this phase)

## Success Criteria (translated for executable verification)
1. `build_sources()` returns 7 instances, each implementing `SourcePort`.
2. `crawler run-once --top-n 30` against the live internet exits 0 and produces `topic_sources` rows with `source_name` ∈ {hackernews, reddit_all, reddit_business, reddit_retail, reddit_bifl, nyt_homepage, google_news} (subset acceptable if a source is rate-limited that minute, but ≥5 of 7 must succeed).
3. Cross-source dedup test (mocked NYT + Google News fixtures with the same headline) produces one `topic` row and two `topic_sources` rows.
4. A single source raising mid-fetch does NOT abort the run — verified by an orchestrator unit test with a deliberately failing fake source alongside two healthy ones.
5. Each `topic_sources.native_rank` matches the rank assigned by its source adapter (per-source, 1-based).
6. Plan-level grep verification still passes: no AI imports in ingest, single Alembic tree, no scheduler, layer purity in `domain/`.
