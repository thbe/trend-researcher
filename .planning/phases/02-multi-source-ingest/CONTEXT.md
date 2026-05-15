# Phase 2 Context: Multi-Source Ingest

> **Reality update from Plan 02-04 live smoke (2026-05-15):** This phase
> was planned for 7 sources (HN + 4 Reddit + 2 RSS) but ships **3** —
> Reddit was dropped after the live smoke confirmed a hard datacenter-IP
> WAF block (see "Reddit access reality" below). The dedup hot-fix
> (find_candidates window 50→5000) was also discovered and shipped during
> the same smoke. The original Phase 2 goal — "fan out across multiple
> sources, dedup across them, never abort on a single source failure" —
> is met by the 3 sources that do work.

## Goal
Onboard the remaining v1 sources behind the source-plugin contract from Phase 1. After this phase, a single `crawler run-once` invocation fans out across **multiple sources** and every distinct trending story shows up exactly once in `topics`, with one `topic_sources` row per (source, observation).

## Locked Decisions (carried into Phase 2 plans)

### Source set (final, no TBDs)
| # | Source           | Adapter type     | Endpoint                                                                  | v1 status         | Why                                  |
|---|------------------|------------------|---------------------------------------------------------------------------|-------------------|--------------------------------------|
| 1 | `hackernews`     | JSON (Firebase)  | (already in Phase 1)                                                      | **shipped**       | tech leading indicator               |
| 2 | `reddit_all`     | JSON (Reddit)    | `https://www.reddit.com/r/all/hot.json`                                   | dropped (WAF)     | broad zeitgeist / virality           |
| 3 | `reddit_business`| JSON (Reddit)    | `https://www.reddit.com/r/business/hot.json`                              | dropped (WAF)     | macro / company news                 |
| 4 | `reddit_retail`  | JSON (Reddit)    | `https://www.reddit.com/r/retail/hot.json`                                | dropped (WAF)     | direct domain                        |
| 5 | `reddit_bifl`    | JSON (Reddit)    | `https://www.reddit.com/r/BuyItForLife/hot.json` (**user pick**)          | dropped (WAF)     | consumer demand for durable products |
| 6 | `nyt_homepage`   | RSS (XML)        | `https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml`               | **shipped**       | mainstream agenda                    |
| 7 | `google_news`    | RSS (XML)        | `https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en`                   | **shipped**       | aggregated headlines, dedup partner  |

The `RedditJsonSource` adapter is kept in `crawler.adapters.sources.reddit` (still has unit tests + works on residential IPs) but is **not** registered in `build_sources()`. Re-enabling Reddit requires either running from a residential IP or adding OAuth (see "Reddit access reality").

### Reddit access reality (Plan 02-04 finding)
- Plain-`curl` GET to `https://www.reddit.com/r/<sub>/hot.json` from inside the Docker network with our polite UA → **HTTP 200**.
- Identical request via `httpx.AsyncClient` from the **same** Docker network with the **same** UA → **HTTP 403 Blocked**.
- Reddit `/.rss` endpoint shows the same split: `curl` 200, `httpx` 403.
- Conclusion: Reddit's Cloudflare WAF fingerprints the TLS / HTTP-client stack, not just the User-Agent. CONTEXT.md originally anticipated 429 (rate-limit); the actual signal is 403 (block).
- The WAF is also IP-class sensitive — same `httpx` request from a residential IP returns 200 (operator confirmed manually).
- Mitigations evaluated: (A) Reddit OAuth via registered app → out of scope for v1, tracked as Phase 3+ follow-up, would require client_id/secret, refresh-token handling, and a separate adapter; (B) drop Reddit entirely → **chosen for v1**; (C) Reddit RSS (`/.rss`) → also blocked by httpx, dead end; (D) tweak httpx settings (HTTP/2, custom ssl context) → not pursued, would be a research detour against an actively-maintained WAF.
- Decision: Phase 2 ships HN + NYT + Google News. Reddit is documented and deferred.

### Schema decision
**No schema changes in Phase 2.** Phase 1 already shipped `Topic.observation_count` (denormalized counter, bumped per re-observation) and `Topic.last_seen_at` (denormalized timestamp, bumped per re-observation). The repository's `update_existing` already increments both. Cross-source dedup uses the same `find_candidates` + `is_duplicate` path — no new tables, no new columns. (The earlier "row-per-observation vs counter" debate was based on an incorrect read of the model; the schema already matches the desired option.)

### Dedup window hot-fix (Plan 02-04 finding)
- Phase 1's `SqlAlchemyTopicRepository.find_candidates` was a recent-window scan with `limit=50`. Worked for the single-source 30-topic Phase 1 smoke; silently broke the moment the DB grew past 50 topics — older topics fell outside the window and were re-inserted on the next crawl instead of bumping `observation_count`.
- Hot-fixed in commit `da6dcee` by widening the default `limit` to 5000 (port contract, repo, and orchestrator call site updated together). Regression test pins the new behaviour.
- This is a Phase 2 patch, not the proper fix. Phase 3 will replace the recent-window scan with an indexed lookup on a `dedup_key` column.

### Cross-source dedup
- The Phase 1 dedup primitives (`dedup.dedup_key` + `dedup.is_duplicate`, threshold 85, rapidfuzz `token_set_ratio`) are **source-agnostic** by design.
- A story appearing on NYT and Google News will already collapse to one `topic` row with **two** `topic_sources` rows (different `source_name`, possibly different `url`).
- The `find_candidates` recent-window scan in `SqlAlchemyTopicRepository` is also source-agnostic.
- **Therefore cross-source dedup needs no new code.** It needs a **test** to prove it. (Plan 02-03 T02 shipped 3 such tests.)

### Native rank preservation
Each source writes its own `native_rank` to its own `topic_sources` row. No cross-source normalization. Phase 1 already enforces this; Phase 2 just inherits.

### Orchestrator behavior
The Phase 1 orchestrator (`crawler.app.orchestrator.run_once`) already iterates over `sources: list[SourcePort]` from the composition root. Phase 2 just **registers more adapters in `build_sources()`**. The orchestrator code itself does not change (Plan 02-03 T01 only added a `failed_sources` list to the result dict — backward-compat additive).

### Per-source failure isolation
A single source failing (network error, malformed payload, rate limit) **must not** abort the whole run. The orchestrator's per-source loop catches + logs + continues. (Phase 1 already had isolation; Plan 02-03 T01 added the named-failure list.)

### HTTP / politeness
- Reddit anonymous endpoints are blocked from datacenter IPs regardless of User-Agent (see "Reddit access reality" above). The polite UA `Trend-Researcher/0.1 (internal PoC; +https://github.com/thbe/trend-researcher)` is still set on Reddit (and all other) requests for when Reddit becomes reachable.
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
- Trigram index on `topics.title` (still recent-window scan; Phase 2 hot-fix raised the window to 5000; Phase 3 replaces with indexed lookup).
- Scheduling — still operator-invoked one-shot, scheduler is Phase 3.
- **Reddit OAuth** — anonymous JSON is WAF-blocked from datacenter IPs (see "Reddit access reality"); OAuth scaffold deferred to Phase 3+ if/when Reddit data is needed.
- A "sources registry" table — `build_sources()` list is fine; `crawl_config` table is Phase 5.
- UI of any kind.
- AI / assessment of any kind (ARC-001 hard rule).

## References (live code, not aspirational)
- `services/crawler/src/crawler/ports/source_port.py` — protocol new adapters implement
- `services/crawler/src/crawler/adapters/sources/hackernews.py` — reference adapter
- `services/crawler/src/crawler/adapters/sources/reddit.py` — Reddit adapter (kept, NOT registered — see "Reddit access reality")
- `services/crawler/src/crawler/adapters/sources/rss.py` — RSS adapter
- `services/crawler/src/crawler/app/composition.py` — `build_sources()` registration point
- `services/crawler/src/crawler/app/orchestrator.py` — `run_once` loop
- `services/crawler/src/crawler/domain/dedup.py` — source-agnostic dedup
- `packages/core/src/core/models.py` — schema (no changes this phase)

## Success Criteria (translated for executable verification)
1. `build_sources()` returns 3 instances (HN + NYT + Google News), each implementing `SourcePort`. (Originally specified 7; Reddit dropped — see "Reddit access reality".)
2. `crawler run-once --top-n 30` against the live internet exits 0 and produces `topic_sources` rows with `source_name` ⊆ {hackernews, nyt_homepage, google_news}, ≥3 of 3 sources succeeding (Reddit removed from the registered set).
3. Cross-source dedup test (mocked NYT + Google News fixtures with the same headline) produces one `topic` row and two `topic_sources` rows. **Shipped in Plan 02-03 T02.**
4. A single source raising mid-fetch does NOT abort the run — verified by orchestrator unit tests with deliberately failing fake sources alongside healthy ones. **Shipped in Plan 02-03 T01.**
5. Each `topic_sources.native_rank` matches the rank assigned by its source adapter (per-source, 1-based). **Shipped Phase 1; per-adapter unit tests pin behaviour.**
6. Plan-level grep verification still passes: no AI imports in ingest, single Alembic tree, no scheduler, layer purity in `domain/`.
7. **(Plan 02-04 addition)** `find_candidates` default window is wide enough that a topic ingested by source A is still found when source B re-observes it on the next crawl — even after the DB has grown past the old 50-row Phase 1 limit. Pinned by regression test.
