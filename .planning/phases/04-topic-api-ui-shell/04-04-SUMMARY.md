# Plan 04-04 — Vuetify SPA scaffold at `web/` — SUMMARY

**Phase:** 4 — Topic API & UI Shell
**Plan:** 04-04 (Wave 4 of 6)
**Status:** ✅ all 6 tasks complete; runtime acceptance (`npm run dev` end-to-end against compose stack) deferred to operator batch with 04-05 T07 smoke.

## Tasks completed

| #   | Commit    | Description                                              |
| --- | --------- | -------------------------------------------------------- |
| T01 | `5dc5af2` | bootstrap `package.json` + lock + `.nvmrc` + `.gitignore` |
| T02 | `c778a05` | `vite.config.ts` + `tsconfig*.json` + `index.html` + `env.d.ts` |
| T03 | `03ecda0` | `main.ts` + Vuetify plugin + router + typed API client + format helpers |
| T04 | `f751426` | `TopicList.vue` with `v-data-table-server` + API-side sort |
| T05 | `c5927f6` | `TopicDetail.vue` with sources list + raw metadata accordion |
| T06 | `58cfcbe` | `web/README.md` — 6 sections incl. npm audit baseline    |

## Acceptance gates passed in-process

- `npm run typecheck` → exit 0 (vue-tsc strict on all .vue + .ts files)
- `npm run build` → exit 0; `dist/` produced
  - Main chunk: ~69 KB gz (Vue + Vuetify shell)
  - Lazy `TopicList` chunk: ~38 KB gz JS + ~6 KB gz CSS
  - Lazy `TopicDetail` chunk: ~6 KB gz JS
  - Shared lazy chunk (`v-list`, `v-chip`, etc.): ~22 KB gz
- Same-origin guard: `grep -nE 'http://|https://|VITE_'` over
  `src/api/{client,topics}.ts` → only matches are in code comments. No
  runtime absolute URLs or env vars. (CONTEXT G8.)
- `target="_blank"` paired 1:1 with `rel="noopener noreferrer"` in
  `TopicDetail.vue` (single hit, threat-model bullet honored).
- STO-006 trace: `web/src/api/topics.ts` field types mirror
  `services/api/src/api/schemas.py` 1:1 (incl. `breadth: number` +
  `longevity_seconds: number`); SPA never computes breadth/longevity.

## G-decisions honored

- **G1:** Vuetify 3 + Vite 5 + npm + Vue Router 4 + MDI + Roboto via
  `@fontsource/roboto` (self-hosted, no Google Fonts CDN).
- **G2:** SPA built into `dist/`, to be served by FastAPI
  `StaticFiles(html=True)` in 04-05; relative `/api/*` fetches resolve
  same-origin in prod, via Vite proxy in dev.
- **G5:** TopicList sort column keys (`breadth`, `longevity_seconds`,
  `last_seen_at`) translated to the API whitelist (`breadth`,
  `longevity`, `last_seen_at`) via `SORT_KEY_MAP` and prefixed with `-`
  for desc. Default `-last_seen_at`. `limit` clamped at the table to
  `[10, 20, 50, 100]`.
- **G7:** detail view consumes `GET /api/topics/{id}` typed response and
  surfaces `topic_metadata` (object) + `sources[]` (5 fields, no
  `raw_payload`).
- **G8:** zero base-URL, zero `VITE_*` env. `fetch("/api/...")` only.

## UI-SPEC contract surfaces

- **60/30/10 color discipline:** primary Punch Red (#EF233C) reserved for
  the external-link icon, hover tints, and sort chevron (Vuetify
  defaults). Secondary slate (#62727B) on the app bar. Neutral surfaces
  dominate.
- **Column copy:** "Sources" not "breadth"; "Observed" not "longevity".
- **`formatLongevity` buckets:** `<60s → '<1m'`; `<3600 → 'Nm'`;
  `<86400 → 'Nh'`; else `'Nd'` or `'Nd Nh'` if non-zero hour remainder.
- **Truncation:** title > 80 chars → first 79 + ellipsis; source URL > 60
  chars → middle-truncated (first 30 + ellipsis + last 27).

## Files touched (final state)

| Path                                       | Lines | Notes                              |
| ------------------------------------------ | ----- | ---------------------------------- |
| `web/package.json`                         |   25  | trend-researcher-web 0.1.0         |
| `web/package-lock.json`                    | (lock) | 58 packages installed              |
| `web/.nvmrc`                               |    1  | `20`                               |
| `web/.gitignore`                           |    4  | node_modules, dist, .vite, *.local |
| `web/vite.config.ts`                       |   35  | proxy /api -> :8000                |
| `web/tsconfig.json`                        |   29  | strict, path alias `@/*`           |
| `web/tsconfig.node.json`                   |   13  | composite for build-tool config    |
| `web/env.d.ts`                             |    7  | vite/client + *.vue shim           |
| `web/index.html`                           |   11  | mounts #app                        |
| `web/src/main.ts`                          |   14  | mounts router + vuetify            |
| `web/src/plugins/vuetify.ts`               |   33  | thbeLight palette                  |
| `web/src/router/index.ts`                  |   25  | / + /topics + /topics/:id          |
| `web/src/App.vue`                          |   23  | v-app shell + secondary app-bar    |
| `web/src/api/client.ts`                    |   38  | ApiError + request<T> (same-origin)|
| `web/src/api/topics.ts`                    |   48  | Topic/Source/Detail types          |
| `web/src/lib/format.ts`                    |   27  | longevity buckets                  |
| `web/src/views/TopicList.vue`              |  166  | v-data-table-server                |
| `web/src/views/TopicDetail.vue`            |  194  | detail + sources list              |
| `web/README.md`                            |   90  | dev / build / typecheck / audit    |

## Deferred-acceptance batch additions (items 11–13)

Operator runs these together with items 1–10 (postgres-bound from 04-01..04-03)
after `docker compose up -d postgres api` (and after 04-05 smoke):

11. `cd web && npm run dev` then open `http://localhost:5173/topics` →
    list renders (empty state until items 5/9 produce real rows).
12. Click any row → navigates to `/topics/:id`; back button returns to list.
13. Click an external source URL → opens in a new tab with no referrer
    leak (DevTools Network shows no `Referer` header for the navigation).

## Carry-forward to 04-05

- `web/dist/` is the artifact 04-05 needs to mount via FastAPI
  `StaticFiles(directory=get_web_dist_dir(), html=True)` AFTER all
  `/api/*` routers are registered (CONTEXT G2 order).
- Production Dockerfile (Ubuntu + postgresql-16, 3-stage) builds the SPA
  in the node stage and copies `dist/` into the final image.
- `npm run build` is idempotent and deterministic across the same Node
  major + lock file — the Dockerfile's node stage will use the committed
  `package-lock.json` for reproducibility.

## Inline plan-checker self-verify

PASS 11/11 (frontmatter, goal, atomic tasks, binary AC, vertical slice,
threat model 7 bullets, out-of-scope 5 bullets, must-haves 8 bullets,
deps declared on 04-03, autonomous=true, REQ traceability UI-001 +
UI-002 covered).
