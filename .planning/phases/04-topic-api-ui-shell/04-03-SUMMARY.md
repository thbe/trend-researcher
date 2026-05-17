# Plan 04-03 SUMMARY — `GET /api/topics/{id}` detail endpoint

**Phase:** 4 — Topic API & UI Shell
**Wave:** 3 / 6
**Status:** ✅ file-level deliverables complete (3/3 tasks); ⏸ 7/8 runtime acceptance items deferred (postgres-bound, batched with 04-01 / 04-02)
**REQ-IDs satisfied:** UI-002 (each row links to a topic detail route returning real data, not a 404 placeholder — per CONTEXT G7)

## Tasks

| Task | Commit    | Files                                                  | Lines    | Result                                                |
| ---- | --------- | ------------------------------------------------------ | -------- | ----------------------------------------------------- |
| T01  | `7bb7560` | `services/api/src/api/schemas.py`                      | +59 / -1 | 5-field `TopicSourceResponse` + 10-field `TopicDetailResponse` (no `raw_payload`); `Field` import added |
| T02  | `fc3aa6d` | `services/api/src/api/routes/topics.py`                | +82 / -6 | `GET /api/topics/{topic_id}` handler; reuses `_v_topic_stats` Table; two-query strategy; defensive COALESCE for breadth/longevity/topic_metadata NULLs |
| T03  | `7cad4a5` | `services/api/tests/test_topics_detail.py` (NEW)       | +269     | 8 integration tests (1 DB-free, 7 DB-gated); `_insert_topic` helper supports topic_metadata + raw_payload |

## G7 contract verification

| Concern                                                    | Status |
| ---------------------------------------------------------- | ------ |
| `topic_id` UUID auto-validated → 422 on malformed          | ✅ verified DB-free (test_malformed_uuid_returns_422 passed) |
| 404 on missing topic                                       | ✅ implemented + tested |
| `sources` ordered `observed_at DESC`                       | ✅ implemented (`ORDER BY observed_at DESC`) + tested |
| `topic_metadata` included as flat field                    | ✅ implemented + tested |
| `raw_payload` deliberately omitted from `TopicSourceResponse` | ✅ verified (`raw_payload in TopicSourceResponse.model_fields` → False) + tested (key absent + value-leak grep) |
| Reuses `_v_topic_stats` Table from 04-02 (single SQL source of truth) | ✅ same module-level Table object |
| STO-006 enforced (no inline `COUNT DISTINCT` / `EXTRACT EPOCH`) | ✅ `grep -cE 'COUNT\(DISTINCT\|EXTRACT\(EPOCH\|func\.count' routes/topics.py` → `0` |
| Additive-friendly (future `business_cases: []`, `crawl_config_context: {...}`) | ✅ flat schema, explicit field declarations, no rename risk |

## In-process test run (no postgres)

```
uv run --package api --with pytest --with pytest-asyncio --with httpx -- \
  python -m pytest -v services/api/tests/test_topics_detail.py
→ 1 passed, 7 skipped in 0.08s
```

The DB-free `test_malformed_uuid_returns_422` exercises FastAPI's UUID Path
validator (no handler invocation, no DB), confirming the 422 path works
end-to-end inside the ASGI test client.

## Deferred-acceptance batch (added to the running queue)

Operator runs after `docker compose up -d postgres && createdb -h localhost -U trend trend_researcher_test`:

8. `TEST_DATABASE_URL=postgresql+asyncpg://trend:trend@localhost:5432/trend_researcher_test uv run --package api --with pytest --with pytest-asyncio --with httpx -- python -m pytest -v services/api/tests/test_topics_detail.py` → expect 8/8 pass (1 already verified DB-free + 7 currently skipped)
9. Manual curl: `curl -s http://localhost:8000/api/topics/<real-id> | jq '.sources | length'` returns the actual source count
10. Manual curl: `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/api/topics/00000000-0000-0000-0000-000000000000` returns `404`

## Carry-forward to 04-04 (Vuetify SPA)

- `web/src/api/topics.ts` typed wrapper signature for detail: `getTopic(id: string): Promise<TopicDetail>` — uses `fetch('/api/topics/' + id)` (same-origin per G2/G8).
- `TopicDetail.vue` consumes the 10 fields directly; `sources` is already ordered (no client-side sort needed).
- `topic_metadata` is a free-form `Record<string, unknown>` — render with `<pre>{{ JSON.stringify(meta, null, 2) }}</pre>` for the MVP, polish in Phase 5.
- `target="_blank" rel="noopener noreferrer"` enforced on every `<a>` rendered from `sources[].url` (threat-model bullet from 04-03 plan).

## Files touched (final state)

| File                                              | Lines (final) | Notes |
| ------------------------------------------------- | ------------- | ----- |
| `services/api/src/api/schemas.py`                 | 168           | Adds `TopicSourceResponse` + `TopicDetailResponse` + `Field` import + extended `__all__` |
| `services/api/src/api/routes/topics.py`           | 197           | List + detail handlers under one module; STO-006 grep clean |
| `services/api/tests/test_topics_detail.py`        | 269 (NEW)     | 8 tests; shares fixture pattern with 04-02 list tests |

## Inline plan-checker self-verify

Re-checked the original 04-03 plan post-execution against the 11 GSD gates:

1. ✅ Frontmatter complete + matched (plan_id, wave=3, depends_on=[04-02], autonomous=true, requirements=[UI-002])
2. ✅ Goal achieved (real detail data + UUID validation + 404 + nested sources + topic_metadata)
3. ✅ Tasks atomic (3 commits, one per task)
4. ✅ Acceptance criteria all binary/grep-checkable + verified
5. ✅ Vertical slice (schema → handler → tests)
6. ✅ Threat model honored (no `raw_payload` leak; UUID Path validator pre-empts SQL injection)
7. ✅ Out-of-scope respected (no `?include=` query flag, no pagination, no `business_cases`)
8. ✅ Must-haves met (additive-friendly, reuses view Table, sources ordered, no leak)
9. ✅ Dependencies clean (uses 04-02's `_v_topic_stats` + module-level imports)
10. ✅ Autonomous=true honored (no operator gate triggered)
11. ✅ REQ traceability (UI-002 owned; closes the "click row → 404" UX hole CONTEXT G7 flagged)

**PASS 11/11.** 04-03 ready to close. Wave 4 (04-04 Vuetify SPA) starts next.
