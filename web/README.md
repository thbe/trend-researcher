# web/

Vuetify 3 + Vite 5 + Vue 3 SPA for the Trend Researcher control plane.

## Purpose

Internal single-operator UI for browsing the topic store produced by the
Stage-1 crawler. Two views:

- **`/topics`** — Vuetify `v-data-table-server` over `GET /api/topics`
  with API-side sort (`breadth | longevity | last_seen_at`, optional
  leading `-` for desc) and `limit` (1–100). Rows are clickable.
- **`/topics/:id`** — full detail card: title, description, 5-field
  metadata grid (Sources / Observed / First/Last seen / Observations),
  expandable raw `topic_metadata` JSON, and a sources list (chip + URL
  + `rel="noopener noreferrer"` external links).

No state is persisted client-side. No auth. Same-origin only.

## Prerequisites

- Node 20 LTS (see `.nvmrc`). Newer Node majors work for Vite 5 + Vuetify
  3 — verified on Node 26 — but `.nvmrc` is the published baseline.
- A running API on `http://localhost:8088` (start the compose stack:
  `docker compose up -d postgres api`) for the dev workflow.
  Host port `:8000` is reserved for oMLX on macOS — see project README
  → "Port allocation".

## Dev workflow

```bash
cd web
npm install            # one-time
npm run dev            # Vite on :5173, proxies /api -> :8088
```

`vite.config.ts` proxies any `/api/*` request the SPA makes to the
FastAPI service. The SPA itself never sees an absolute URL or a base-URL
env var (CONTEXT.md G8) — in production (Plan 04-05) FastAPI serves
`dist/` same-origin so the same relative paths resolve unchanged.

## Build

```bash
npm run build          # vue-tsc -b && vite build -> dist/
npm run preview        # serve the production build on :4173
```

`dist/` is consumed by the production Dockerfile (Plan 04-05) and mounted
by FastAPI's `StaticFiles(html=True)` at `/`.

## Type-check

```bash
npm run typecheck      # vue-tsc --noEmit (strict)
```

Run before every commit. `vue-tsc` validates `<script setup lang="ts">`
blocks across `.vue`, `.ts`, and `.tsx` files.

## Frontend dev loop (multi-tenant SPA — Phase 10)

The SPA uses **Pinia** for cross-component state (session, active
department, frameworks) and consumes **OpenAPI-typed** schemas generated
from the FastAPI service.

```bash
npm run gen:api        # fetch http://localhost:8088/openapi.json
                       # -> src/api/generated/api.ts (git-ignored)
```

Re-run `gen:api` after any backend schema or route change so call-site
types stay in sync. The runtime API client (`src/api/client.ts`) is
hand-written; the generated file is consumed where compile-time safety
matters (incremental adoption — full migration is a Phase 11 candidate).

`npm run dev` invokes `gen:api --if-server-up` automatically (predev
hook). If the API isn't running yet, codegen logs a warning, leaves any
previously generated file in place, and proceeds — local boot is never
blocked by a cold backend. The same soft mode runs on `prebuild` so
container builds (which can't reach the API) succeed against the last
committed stub or generated file.

Set `OPENAPI_URL` to point codegen at a different host:

```bash
OPENAPI_URL=https://api.staging.example.com/openapi.json npm run gen:api
```

### State stores

| Store                  | Purpose                                                   |
| ---------------------- | --------------------------------------------------------- |
| `stores/session.ts`    | Logged-in user, departments, active dept id, active role  |
| `stores/frameworks.ts` | System framework catalog + per-dept enabled set + default |

Pinia is installed in `main.ts` **before** the router and Vuetify so that
router guards and component `setup()` can call `useSessionStore()` etc.
without `getActivePinia()` warnings.

### Rename hook (G8)

Every product-name UI string ("Trend Researcher", "Retail", page
titles) is funnelled through `src/lib/strings.ts`. To rename the product,
edit that one file. See its top-of-file comment.

## Routes

| Path             | Component         | Notes                                |
| ---------------- | ----------------- | ------------------------------------ |
| `/`              | redirect          | -> `/topics`                         |
| `/topics`        | `TopicList.vue`   | named route `topics`                 |
| `/topics/:id`    | `TopicDetail.vue` | named route `topic-detail`, `props:true` |

History mode is `createWebHistory` — production FastAPI mount uses
`StaticFiles(html=True)` which falls back to `index.html`, giving the
SPA proper deep-link support.

## npm audit baseline

Baseline captured **2026-05-17**:

- **0 high / 0 critical** vulnerabilities
- **2 moderate**, both dev-only (`esbuild` GHSA-67mh-4wv8-2f99 — dev
  server CORS quirk; localhost-only, accepted)

Re-run `npm audit --omit=dev` before each production deploy. Production
runtime deps are clean.

## Out of scope (this phase / 04-04)

- No client-side auth, cookies, or `localStorage` writes.
- No CORS — same-origin only.
- No state library (no Pinia / Vuex). Components own their own refs.
- No tests in `web/` for this phase (visual smoke at 04-05 T07 is the
  acceptance bar). Vitest can be added later if a v1.x stable UI calls
  for unit coverage.
- No i18n. English only — internal tool.
