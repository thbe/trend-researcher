# Phase 4.5 Discussion Log — Topic Description Capture & URL Resolution

**Status:** Discussing (locked once operator decides Q1–Q5 below)
**Mode:** mvp · `DISCUSS_MODE="discuss"` · `auto_advance=false`
**Triggered by:** operator `m1086` *"I can only see the headline, isn't there more context available for analysis?"* + `m1087` *"do the recommendation"* (during Phase 4 execution; carried as Phase 4.5 follow-up per `04-06-SUMMARY.md` §9.a/b)
**Depends on:** Phase 4 complete (live Cloud Run service + production DB w/ 167 topics)

---

## Background — What we discovered when grounding scope

The "do the recommendation" carried into this phase from Phase 4 turned out to be cheaper than initially modeled. Three facts verified against the live system before opening discussion:

### Fact 1 — `topics.description` column ALREADY EXISTS
```
Table "public.topics"
  description  | text  |  | nullable |
```
Defined in `packages/core/src/core/models.py:41`. No Alembic migration needed for schema work. This collapses **Plan 04.5-01 (migration)** that was assumed in the Phase 4 follow-up sketch.

### Fact 2 — The description bytes are ALREADY IN THE DB, just not surfaced
`services/crawler/src/crawler/adapters/sources/rss.py:109` already stores `entry.summary` into `topic_sources.raw_payload` JSONB:
```python
"summary": entry.get("summary"),
```
Both NYT homepage AND Google News RSS items hit this path (both go through `RSSFeedSource`). So:
- For **new crawls**: the data is there; we just need to plumb it from `RawItem` → `Topic` row.
- For **existing 167 production rows**: the data is sitting in `topic_sources.raw_payload['summary']` waiting to be read. **A one-shot backfill SQL is possible without re-fetching anything.**

### Fact 3 — Google News URLs are `CBM…` base64 redirect tokens
Confirmed live:
```
https://news.google.com/rss/articles/CBMivgFBVV95cUxOX01oWE9KNzhGRWxpNmFremR4bGNGRkZiZi1vb3dVM0dfQUJ…
```
These are Google News' opaque encoded redirect tokens, not publisher URLs. Clicking one in a browser does a JS-driven redirect. The decoded payload contains the destination URL, but the decode is **non-trivial** (protobuf-in-base64, format has changed multiple times in 2024-2025 and there's no public stable spec). Three resolution strategies — see Q3 below.

### Fact 4 — `RawItem` has NO `description` field today
`services/crawler/src/crawler/domain/raw_item.py` — would need an additive `description: str | None = None` field. Domain dataclass, frozen, slots; additive change is ports-clean.

### Fact 5 — Single Topic-creation site
`services/crawler/src/crawler/adapters/persistence/sqlalchemy_topic_repository.py:67` — only place we instantiate `Topic(…)`. One file edit to plumb description through. Merge-on-re-observation is also here.

### Fact 6 — Hacker News carries no description
`HackerNewsSource` is a separate adapter (JSON, not RSS). HN front-page items don't have a snippet/excerpt — only title + url. So `description=None` for all HN topics is the correct, expected outcome.

---

## Scope — what's IN, what's OUT

### IN (this phase)
1. **`RawItem.description: str | None`** — additive domain field.
2. **`RSSFeedSource` parser** — populate `description` from `entry.summary` (already extracted, just hand it off explicitly).
3. **`SQLAlchemyTopicRepository`** — plumb `RawItem.description` into the `Topic` row on first observation; apply merge strategy on re-observation (see Q1).
4. **Backfill** — one-shot SQL/Python script that reads `topic_sources.raw_payload->>'summary'` for existing rows and populates `topics.description` where currently NULL. Run-once, then delete the script (or keep under `scripts/`). Operator-invoked, not in the crawl path.
5. **Google News URL resolution** — strategy locked in Q3 below. Implemented as either a deterministic local decode or a pre-existing redirect that's already in `raw_payload`, depending on Q3 answer.
6. **SPA** — TopicList shows description (truncated), TopicDetail shows full description. Already partially wired schema-side (the API returns `description` field today, just always `null`). Just need template-side rendering + truncation helper.
7. **Tests** — `RawItem` field, parser unit test, repository merge test, backfill script smoke (against local docker postgres).

### OUT (deferred / not in this phase)
- **Hacker News description backfill** — HN doesn't expose one. Skip cleanly.
- **NYT standfirst beyond what's in RSS `<description>`** — the NYT homepage RSS feed's `<description>` IS the standfirst. If operator wants the longer-form dek, that requires scraping the article page itself (new HTTP fetch, ARC-001 risk surface, not free). Phase 5+.
- **Re-fetching old `topic_sources` rows** — anything not already in `raw_payload['summary']` stays NULL. We don't go back to the network.
- **AI-driven summarization** — explicitly forbidden by ARC-001 (Stage 1 is AI-free).
- **Reddit description** — Reddit is still unregistered (Phase 2 reality block); no work needed.
- **Adding `topic_sources.resolved_url` column** — only add IF Q3 picks a strategy that produces a different URL than the one originally stored. Decision deferred until Q3.

---

## Operator Decisions Needed (Q1–Q5)

### Q1 — Merge strategy for `description` on re-observation
A topic seen at T0 has `description="A"`. The same topic is observed again at T1 with `description="B"`. What gets stored?

| Option                | Behavior                                                                                | Pros                                                                  | Cons                                                                                       |
| --------------------- | --------------------------------------------------------------------------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| **A. First-non-empty** | Stick with the first non-null description we ever saw                                   | Stable, deterministic, predictable                                    | Stale if the publisher updates the dek (e.g., breaking news evolves)                       |
| **B. Latest wins**     | Always overwrite with the most recent crawl's description (if non-null)                 | Mirrors `last_seen_at` semantics; reflects current publisher state    | Loses history; volatile if Google News rewrites snippets                                   |
| **C. Longest wins**    | Keep whichever description has more characters                                          | Often picks the most informative version (NYT > Google News snippets) | Bias toward verbosity; non-trivial to reason about                                         |
| **D. Source-priority** | Prefer NYT > Google News > others (when multiple sources contribute to the same topic) | Aligns with editorial trust                                           | Requires per-source ranking config; adds coupling                                          |

**Default recommendation:** **A (first-non-empty)** — matches the existing `first_seen_at` immutability semantic and avoids volatility from Google News rewriting snippets every 12h. If we ever need richer behavior, B is a one-line change later.

> **Operator answer:** _____________

---

### Q2 — Backfill: separate one-shot script vs auto-run on next migration?
The 167 existing topics have NULL descriptions but the underlying `raw_payload` JSONB has the data. Three options:

| Option                                  | What it looks like                                                                       | Pros                                                | Cons                                                                  |
| --------------------------------------- | ---------------------------------------------------------------------------------------- | --------------------------------------------------- | --------------------------------------------------------------------- |
| **A. `scripts/backfill_descriptions.py`** | Operator runs once: `docker compose exec api python -m scripts.backfill_descriptions`     | Explicit, auditable, idempotent, kept in repo       | Operator must remember to run it once after first deploy of this phase |
| **B. Data migration in Alembic 0004**   | Alembic upgrade does a `UPDATE topics SET description = … FROM topic_sources WHERE …`     | Automatic on next deploy; nothing to remember       | Data migrations in Alembic are an anti-pattern in some shops          |
| **C. Skip backfill, only new crawls**   | Wait for the natural re-observation to populate description on the next 12h tick         | Zero new code                                       | First 12h after deploy, only newly-observed topics have descriptions  |

**Default recommendation:** **A (one-shot script)**. Reasons: backfill is one-time, the script is trivially auditable, and we already have a deploy idiom (`docker compose exec`). Keeps Alembic limited to schema, which is a stated convention.

> **Operator answer:** _____________

---

### Q3 — Google News URL resolution strategy
Each Google News item arrives as `https://news.google.com/rss/articles/CBMi…<long base64>…`. Three approaches:

| Option                              | Approach                                                                                                                            | New HTTP?    | Reliability                                                                                       | Effort                                  |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ------------ | ------------------------------------------------------------------------------------------------- | --------------------------------------- |
| **A. Decode the base64 token**      | The `CBM…` token is base64-protobuf containing the destination URL. Several OSS implementations exist (`googlenewsdecoder` PyPI).    | **NONE**     | Medium — Google changes format ~every 6–12 months, breaks decoder. Last breakage was Aug 2024.   | Add 1 dependency + 1 helper + 1 test    |
| **B. Follow the redirect once**     | Issue HTTP HEAD against the Google News URL, capture `Location:` header                                                             | **+1 per item** | High — Google's own redirect always works                                                          | Add 1 httpx call per Google News item   |
| **C. Skip resolution, store as-is** | Leave URLs as `news.google.com/…` redirect tokens; document this is a Google News quirk                                              | **NONE**     | N/A                                                                                               | Zero                                    |
| **D. Hybrid: try A, fall back to C** | Try the decoder; if it fails (raises or returns the same URL), fall back to storing the token as-is. Log decoder breakages.         | **NONE**     | Self-healing — works most of the time, gracefully degrades when Google rotates format              | A's effort + try/except + structlog warn |

**Default recommendation:** **D (hybrid A+C)**. Reasons:
- Operator gets clickable publisher URLs ~95% of the time.
- ARC-001 / no-new-HTTP-fetches preserved (locked phase constraint).
- When Google breaks the format, we get a structlog warn and the system keeps working with raw tokens — no outage.
- B (HEAD follow) adds 38 new outbound HTTP calls per crawl (current Google News crawl size) and adds latency / failure modes to a deterministic ingest path.

**Caveat for D:** if Google changes format and we don't notice, all NEW Google News URLs after that day silently become tokens again. **Mitigation:** add a `crawl_runs` per-source stat `google_news_url_resolution_failures` so the rate is visible in `/api/runs`.

> **Operator answer:** _____________

---

### Q4 — Where does the resolved URL live?
If Q3 = A, B, or D (i.e., we resolve something), there are two storage options:

| Option                                                       | Schema change                                                                                                                                            | Implication                                                                                                                      |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| **A. Overwrite `topic_sources.url`** with the resolved URL    | None — uses existing column                                                                                                                              | Simple, but unique-constraint risk: a Google News URL and the resolved publisher URL are different strings → dedup might re-fire |
| **B. New column `topic_sources.resolved_url TEXT NULLABLE`** | Alembic `0004_topic_sources_resolved_url.py` adding nullable column. Existing rows stay NULL. SPA prefers `resolved_url` when present, falls back to `url`. | Cleanest. Preserves provenance (we know what we originally got). Slightly more DB work.                                          |

**Default recommendation:** **B (new nullable column)** — preserves original URL for debugging Google changes, no migration of existing data needed, SPA logic is `row.resolved_url || row.url`.

> **Operator answer:** _____________

---

### Q5 — SPA rendering footprint
The API already returns `description` and (after Q4) potentially `resolved_url`. SPA work needed:

| Surface                       | Change                                                                                                  | Cost                  |
| ----------------------------- | ------------------------------------------------------------------------------------------------------- | --------------------- |
| **TopicList row**             | Show description truncated to ~120 chars under the title (Vuetify `v-list-item-subtitle` already there) | ~10 lines TS/template |
| **TopicDetail page**          | Show full description as a paragraph above the source list                                              | ~5 lines              |
| **Source-list link**          | Use `resolved_url \|\| url` so the link is human-meaningful                                              | ~3 lines              |
| **(Optional) "(via Google News)" hint** | When `resolved_url` is present, append small caption hint                                       | ~5 lines              |

**Question:** Should we ship all 4, or skip the "(via Google News)" hint as gold-plating?

**Default recommendation:** Ship the first 3, defer the hint (low value, more visual clutter than signal).

> **Operator answer:** _____________

---

## Proposed Plan Shape (post-discuss; CONTINGENT on Q1–Q5 answers)

Assuming the default-recommended answers, Phase 4.5 becomes a **single-plan phase**:

- **Plan 04.5-01: Description capture + Google News URL resolution + backfill** (1 wave, ~6 tasks):
  - T01: Add `description` to `RawItem` + RSS parser hands it off (crawler tests)
  - T02: Alembic 0004 adds `topic_sources.resolved_url` nullable column
  - T03: Google News URL decoder (helper + tests, hybrid A+C fallback)
  - T04: `SQLAlchemyTopicRepository` plumbs description (first-non-empty merge) + writes `resolved_url`
  - T05: `scripts/backfill_descriptions.py` (one-shot, idempotent, reads `raw_payload['summary']`)
  - T06: SPA template updates (TopicList subtitle + TopicDetail paragraph + source-link uses resolved_url) + SUMMARY + ROADMAP `[x]`

If operator picks non-default answers, plan shape may flex (e.g., Q3=B "HEAD follow" adds a SourcePort-level concern and would split into a separate plan).

---

## Constraints Preserved (DO-NOT-BREAK)
- **ARC-001:** No AI in ingest. All description handling is deterministic.
- **No new outbound HTTP fetches** in the crawl path (Q3=D / A / C respect this; Q3=B violates it and would need operator override).
- **Stage 1 / Stage 2 separation:** description goes into the same Postgres rows; Stage 2 (Phase 6+) will read it for RAG.
- **Single Alembic tree in `packages/core`:** only 0004 added if Q4=B.
- **Idempotent backfill:** must be safe to run twice (use `WHERE description IS NULL` guard).
- **Production stability:** changes ship via the same `cloudbuild.yaml` v0.4.x bump; no infrastructure changes.

---

## Awaiting Operator Input
Please answer Q1, Q2, Q3, Q4, Q5 above. Once locked, I'll:
1. Append a "Decisions Locked" section to this file with the chosen options + 1-line rationale per choice.
2. Open `/gsd-plan-phase` to produce `04.5-01-PLAN.md`.
3. Update `STATE.md` `status: phase-planning` and `ROADMAP.md` plan list with the locked plan name.
