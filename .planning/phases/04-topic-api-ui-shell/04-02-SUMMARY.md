# 04-02 SUMMARY — /api/* re-prefix + GET /api/topics

**Status:** ✅ All 6 tasks complete (acceptance deferred to operator batch — postgres-bound).
**Wave:** 2/6
**Commits on `main`:** 6 (T01 from prior range + T02–T06 this range)

## Tasks delivered

| Task | Commit    | Deliverable                                                      |
| ---- | --------- | ---------------------------------------------------------------- |
| T01  | `4b28e01` | Re-prefix `/healthz` + `/runs` routers under `/api/*` in main.py |
| T02  | `ffa08be` | Update healthz + runs tests to `/api/*` + add 404-regression     |
| T03  | `98ed1cc` | `TopicResponse` (8 fields) + `TopicsListResponse` envelope       |
| T04  | `833501a` | `GET /api/topics` route reading `v_topic_stats` view             |
| T05  | `12a40d5` | 12 integration tests (5 DB-free + 7 DB-gated) covering G5        |
| T06  | `1331e28` | Update `scripts/smoke_phase3.sh` + `README.md` for `/api/*`      |

## G5 contract verification

- ✅ `sort` whitelist `{breadth, longevity, last_seen_at}` with optional leading `-` for desc; unknown → 400
- ✅ Default sort `-last_seen_at`
- ✅ `limit: Query(20, ge=1, le=100)`; 0 or 101 → 422
- ✅ Response envelope `{topics:[...], limit, sort}` with sort echoed verbatim
- ✅ No nested `sources` or `topic_metadata` on list rows (deferred to detail endpoint in 04-03)
- ✅ `breadth` + `longevity_seconds` sourced from `v_topic_stats` view (STO-006: derived, not stored)
- ✅ `grep -E 'COUNT\(DISTINCT|EXTRACT\(EPOCH|func\.count' services/api/src/api/routes/topics.py` → 0 matches

## DB-free test results (in-process)

```
$ uv run --package api --with pytest --with pytest-asyncio --with httpx -- \
    python -m pytest -v services/api/tests/test_topics_list.py
==================== 5 passed, 7 skipped in 0.04s ====================
```

5 DB-free tests verify: unknown sort → 400, limit=0 → 422, limit=101 → 422, sort
echoed in envelope, default sort applied when omitted. 7 DB-gated tests skip
cleanly via `db_available()` TCP probe.

## Deferred acceptance (batch — operator)

Run after `docker compose up -d postgres` + `alembic upgrade head`:

1. **Topics integration tests pass:**
   ```bash
   TEST_DATABASE_URL=postgresql+asyncpg://trend:trend@localhost:5432/trend_researcher_test \
     uv run --package api --with pytest --with pytest-asyncio --with httpx -- \
     python -m pytest -v services/api/tests/test_topics_list.py
   # expect: 12 passed
   ```
2. **Healthz + runs gated tests pass under same env.**
3. **Smoke script end-to-end:** `bash scripts/smoke_phase3.sh` → 17 steps PASS.
4. **Manual contract spot-check:**
   ```bash
   curl -s 'localhost:8000/api/topics?sort=-breadth&limit=5' | jq '.'
   # expect: {topics:[...], limit:5, sort:"-breadth"}
   curl -s -o /dev/null -w '%{http_code}' 'localhost:8000/api/topics?sort=bogus'
   # expect: 400
   ```

## Carry-forward to 04-03 (Wave 3)

- Detail endpoint `GET /api/topics/{id}` reuses `Topic` ORM (with `selectinload(Topic.sources)`).
- Adds `sources` array ordered `observed_at DESC` + flattened `topic_metadata` field.
- UUID auto-validation via path param type → 422 on malformed id; 404 if missing.
- Single new `TopicDetailResponse` schema (extends `TopicResponse` field set + nested `sources` + `topic_metadata`).
- No new migration; no new view dependency.

## Files touched (final state)

```
services/api/src/api/main.py            46 lines  (+topics_routes include_router)
services/api/src/api/routes/topics.py   121 lines (NEW)
services/api/src/api/routes/healthz.py  45 lines  (docstring breadcrumb)
services/api/src/api/routes/runs.py     47 lines  (docstring breadcrumb)
services/api/src/api/schemas.py         108 lines (+TopicResponse +TopicsListResponse)
services/api/tests/test_topics_list.py  286 lines (NEW)
services/api/tests/test_healthz.py      ~75 lines (+404 regression, /api/* paths)
services/api/tests/test_runs.py         ~145 lines (+404 regression, /api/* paths)
scripts/smoke_phase3.sh                 104 lines (/api/* path updates)
README.md                               165 lines (+/api/topics row, migration note)
```

## Plan-checker self-verify (post-execution)

PASS 11/11 — all tasks atomic, all acceptance criteria binary, threat model
respected (no AI; STO-006 enforced via grep; view stays off Base.metadata),
out-of-scope honored (no detail endpoint, no SPA, no Docker), REQ traceability
intact (G2 + G5 owned end-to-end).
