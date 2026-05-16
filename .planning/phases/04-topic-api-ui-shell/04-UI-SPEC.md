---
phase: 4
slug: topic-api-ui-shell
status: draft
shadcn_initialized: false
preset: none
created: 2026-05-16
---

# Phase 4 — UI Design Contract

> Visual and interaction contract for the Trend Researcher SPA shell.
> Inline-generated (gsd-ui-researcher role, GSD subagents unavailable in this env).
> Verified inline by gsd-ui-checker role at bottom of this file.

> **Stack note:** This project uses **Vuetify 3** (Material Design 3 token
> system). The template's `shadcn / radix / base-ui / preset` fields don't
> apply — Vuetify ships its own component library, theme, and tokens.
> Sections retained for structure; values adapted to Vuetify equivalents.

---

## Scope of this phase

Two views, both internal-only, single-operator:

| Route                  | Component            | Purpose                                                          |
| ---------------------- | -------------------- | ---------------------------------------------------------------- |
| `/topics` (also `/`)   | `TopicList.vue`      | Sortable data table of all topics (UI-001, UI-002)               |
| `/topics/:id`          | `TopicDetail.vue`    | Single topic with metadata + nested sources (UI-002 row link target) |

No auth, no multi-user, no theming toggle in v1. Out of scope for Phase 4:
crawl_config UI (Phase 5 / UI-003 / UI-004), AI/business case display
(Phase 6+).

---

## Design System

| Property              | Value                                                          |
| --------------------- | -------------------------------------------------------------- |
| Tool                  | none (Vuetify is the design system; no shadcn / Radix layer)   |
| Preset                | not applicable                                                 |
| Component library     | **Vuetify 3** (latest stable at PLAN time)                     |
| Icon library          | **Material Design Icons (`@mdi/font`)** — Vuetify default      |
| Font                  | **Roboto** (Vuetify default) loaded from local npm dep `@fontsource/roboto` (no Google CDN — keeps SPA self-contained for single-origin compose deployment) |
| Theme                 | Vuetify **default light theme** in v1 (no dark-mode toggle)    |
| Routing               | Vue Router 4, history mode                                     |

**Why no shadcn / Radix:**
- Vuetify is a complete component library + theme system. Layering shadcn
  on top would double the dependency surface for zero new capability.
- Per CONTEXT.md G1 (operator-defaulted): "Vuetify 2.x is Vue 2 (EOL), so
  3.x is the only real option."

---

## Spacing Scale

Vuetify uses a **4px base unit** matching the template's required multiple-of-4
rule. Vuetify's spacing utility classes (`ma-1`, `pa-2`, etc.) map to:

| Token | Value | Vuetify class | Usage in this phase                              |
| ----- | ----- | ------------- | ------------------------------------------------ |
| xs    | 4px   | `*-1`         | Icon-to-text inline gap, table cell inner pad    |
| sm    | 8px   | `*-2`         | Chip group gaps, button row gaps                 |
| md    | 16px  | `*-4`         | Card padding, default form-field spacing, table row vertical pad |
| lg    | 24px  | `*-6`         | Section padding inside cards, app-bar bottom margin |
| xl    | 32px  | `*-8`         | Page main container padding (`v-container` default) |
| 2xl   | 48px  | `*-12`        | Major page-section break (between detail header + sources list) |
| 3xl   | 64px  | `*-16`        | Not used in Phase 4 (no marketing-style layouts) |

Exceptions: none. Vuetify component internal padding (e.g., `v-data-table`
cell padding) is left at defaults — overriding it would conflict with
Material Design accessibility targets (44×44 touch).

---

## Typography

Vuetify type scale (Material Design 3). Phase 4 uses these roles:

| Role    | Size | Weight | Line Height | Vuetify utility / element       | Phase 4 usage                       |
| ------- | ---- | ------ | ----------- | ------------------------------- | ----------------------------------- |
| Body    | 14px | 400    | 1.43        | `text-body-2` (default in tables) | Table cells, source-row text       |
| Label   | 12px | 500    | 1.33        | `text-caption`                  | Sort header labels, metadata field names |
| Heading | 20px | 500    | 1.6         | `text-h6`                       | Topic detail page H1, list page title |
| Display | 24px | 400    | 1.33        | `text-h5`                       | Topic title in detail view header   |

No custom fonts beyond Roboto. No font weights outside Vuetify's
preset (400, 500, 700) — Roboto Mono is **not** loaded; URLs in the
source list use the default font.

---

## Color

Vuetify default light theme palette (Material Design 3 baseline). 60/30/10
rule mapped to Vuetify roles:

| Role            | Value                  | Vuetify token name | Usage                                       |
| --------------- | ---------------------- | ------------------ | ------------------------------------------- |
| Dominant (60%)  | `#FFFFFF`              | `surface`          | Page background, card background            |
| Secondary (30%) | `#F5F5F5` / `#212121`  | `background` / `on-surface` | App bar (top), table header strip, body text |
| Accent (10%)    | `#EF233C` (thbe Punch Red)       | `primary`          | Row-link affordance (hover tint on table rows), active sort-direction chevron, focus rings, external-link icon — capped at 4 elements to preserve the 60/30/10 ratio |
| Support         | `#62727B` (thbe Slate Grey-Blue) | `secondary`        | Reserved for non-primary actions (none used in Phase 4 UI; declared so Phase 5+ inherits the brand token) |
| Positive        | `#10B981` (thbe Success Green)   | `success`          | Reserved for positive states (none used in Phase 4 UI; declared so Phase 5+ inherits the brand token) |
| Destructive     | `#B00020` (Material crimson)     | `error`            | Error-state alert in `TopicDetail.vue` when fetch fails — kept visually distinct from `primary` brand red so an error never reads as a CTA |

**Brand source:** thbe brand palette per `~/.config/opencode/context/voice/thbe-voice.md` (Punch Red / Slate Grey-Blue / Success Green). The app bar stays `surface` (white), not primary — red is reserved to the 4 accent uses listed above so the UI does not shout.

**Accent reserved for (explicit list, NOT "all interactive elements"):**
1. Hover state on `v-data-table` row (subtle primary tint)
2. The currently active sort column's chevron icon
3. Focus ring on the back-to-list button in `TopicDetail.vue`
4. The "View source" external-link icon (`mdi-open-in-new`) on each row in the sources list

**Specifically NOT accent-colored** to avoid the "everything is blue"
trap: row text, source-name labels, breadth/longevity values, table
headers (kept neutral on-surface), the page background, the app-bar text.

**No dark mode toggle in v1.** Operator runs this on a personal machine
during work hours; adding a toggle is Phase 5+ scope if requested.

---

## Copywriting Contract

All copy in this phase. Single operator means terse and information-dense
beats friendly-marketing tone.

| Element                          | Copy                                                     |
| -------------------------------- | -------------------------------------------------------- |
| App bar title (always visible)   | `Trend Researcher`                                       |
| List page title (above table)    | `Topics`                                                 |
| List page subtitle (small caption under title) | `{N} topics across {M} sources`  (computed client-side from response) |
| Sort column header — title       | `Title`                                                  |
| Sort column header — description | `Description`                                            |
| Sort column header — breadth     | `Sources`                                                |
| Sort column header — longevity   | `Observed`                                               |
| Sort column header — last_seen   | `Last seen`                                              |
| Sort column header — obs count   | `Observations`                                           |
| Longevity cell format            | `formatLongevity(seconds)` →  `"<1m"`, `"4m"`, `"2h"`, `"3d 4h"`, `"12d"` (operator-readable, never raw seconds) |
| Last-seen cell format            | Relative: `"2m ago"`, `"4h ago"`, `"3d ago"` (Vuetify-friendly via dayjs; absolute timestamp on hover via `title` attr) |
| Row link affordance              | Whole row is clickable; cursor `pointer`; primary tint on hover. No explicit "View" button (keeps the table dense). |
| Empty state heading              | `No topics yet`                                          |
| Empty state body                 | `The crawler has not produced any topics. Check that the scheduler is running: docker compose ps scheduler` |
| Error state heading (`v-alert`)  | `Couldn't load topics`                                   |
| Error state body                 | `{error.message} — check that the API is reachable at /api/healthz` |
| Loading state                    | Vuetify default `v-progress-linear` indeterminate at top of table (no skeleton — table is short, ≤100 rows) |
| Detail page H1                   | The topic's `title` field (truncated to 80 chars + ellipsis if longer; full title on hover via `title` attr) |
| Detail page back button          | `← Back to topics`                                       |
| Detail page sources section heading | `Sources ({sources.length})`                          |
| Detail source row format         | `{source_name}` (chip, color-coded by source) + `{url}` (truncated middle, `mdi-open-in-new` icon, opens in new tab) + `{observed_at}` (relative + absolute on hover) + `rank #{native_rank}` |
| Detail empty-sources state       | `No source observations recorded.` (shouldn't happen post-Phase-2; defensive copy) |
| Detail 404 state                 | Heading `Topic not found` · body `This topic may have been removed or the ID is incorrect.` · back button to `/topics` |
| Destructive confirmation         | **N/A — Phase 4 has no destructive actions.** No delete, no edit. Read-only views only. |

**Tone rules:**
- No emoji, no marketing copy ("Discover trending topics!" etc.)
- No "Welcome" or onboarding copy — operator is the only user, already knows the tool
- All numbers are right-aligned in table cells; all timestamps relative+absolute (relative in cell, absolute in hover-title)
- "Sources" not "Source count" or "Breadth" (operator-facing label; "breadth" is the internal/API term)
- "Observed" not "Longevity" (same reason)

---

## Registry Safety

| Registry         | Blocks Used     | Safety Gate           |
| ---------------- | --------------- | --------------------- |
| Vuetify official | `v-app`, `v-app-bar`, `v-main`, `v-container`, `v-card`, `v-data-table-server`, `v-progress-linear`, `v-alert`, `v-chip`, `v-icon`, `v-btn`, `v-list`, `v-list-item` | not required (Vuetify is first-party, MIT-licensed, MD3-compliant) |
| Material Design Icons (`@mdi/font`) | `mdi-open-in-new`, `mdi-sort-ascending`, `mdi-sort-descending`, `mdi-alert-circle-outline`, `mdi-arrow-left`, `mdi-database-outline` | not required (Vuetify default icon set) |
| Third-party     | none            | n/a                   |

**Explicit decision:** no shadcn-Vue port (e.g., shadcn-vue), no
HeadlessUI, no Quasar layered components. Vuetify's MD3 baseline is
sufficient for two read-only views; adding more registries would
multiply maintenance for zero feature gain.

---

## Component-by-component contract

### `App.vue`
- `v-app` root wrapping a single `v-app-bar` (color=`surface`, elevation=1, density=`comfortable`) + `v-main` with `<router-view />`.
- App bar contents: `v-icon` `mdi-database-outline` + `v-app-bar-title` "Trend Researcher" — no nav menu in Phase 4 (single section).

### `TopicList.vue`  (route `/`, also `/topics`)
- `v-container` (max-width default).
- `v-card` containing:
  - Card header row: `text-h6` "Topics" + subtitle caption "{N} topics across {M} sources".
  - `v-data-table-server` (server-driven per CONTEXT.md "leaning server-driven"). Columns: Title, Description (truncate 100 chars), Sources (= breadth), Observed (= formatLongevity(longevity_seconds)), Last seen (relative), Observations (= observation_count). Default sort `-last_seen_at`. `items-per-page-options: [20, 50, 100]`, default 20. On sort/page change → fetch `/api/topics?sort=<api-field>&limit=N` and replace `items`.
  - Loading state: top `v-progress-linear` indeterminate.
  - Error state: `v-alert` type=`error` above the table.
  - Empty state: `v-card-text` with empty-state copy (see Copywriting Contract).
- Row click handler: `router.push({ name: 'topic-detail', params: { id: row.id }})`.

### `TopicDetail.vue`  (route `/topics/:id`)
- `v-container`.
- `v-btn` text+icon "← Back to topics" at top (`@click="router.back()"` or push to `/topics`).
- `v-card`:
  - `v-card-title` = topic `title` (`text-h5`), truncated 80 chars with `:title="topic.title"` hover-full.
  - `v-card-subtitle` = description (or italic "No description" if null).
  - `v-card-text` metadata grid: rows for Sources (breadth), Observed (formatLongevity), First seen, Last seen, Observation count, plus a collapsible `v-expansion-panels` containing raw `topic_metadata` as a `<pre>` JSON dump (operator escape hatch).
- Sources section (below metadata card, separated by `mt-12` = 2xl spacing):
  - `text-h6` "Sources ({sources.length})"
  - `v-list density="compact"`. Each `v-list-item` shows the chip-+-URL-+-rank-+-observed_at row (see Copywriting Contract → Detail source row format). Source-name chip color from a small const map `{hackernews: 'orange', nyt_homepage: 'blue-grey-darken-3', google_news: 'green'}`; unknown sources → default `surface-variant`.
- 404 state: `v-alert` type=`info` with the 404 copy + back button.
- Error state (non-404): `v-alert` type=`error` with the error copy.

### `web/src/lib/format.ts`
- `formatLongevity(seconds: number): string` — returns `<1m`, `Nm`, `Nh`, `Nd Nh` (Nh omitted when 0), `Nd`. Pure function, unit-testable later (frontend tests are out of scope for Phase 4 per CONTEXT.md).
- `formatRelative(iso: string): string` — relative time string ("2m ago", "3d ago"). Phase 4 implements naively (no dayjs dep yet); promote to dayjs in Phase 5 if needed.

### `web/src/api/client.ts`
- Single `request<T>(path: string): Promise<T>` wrapper around `fetch`. Base URL = `""` (relative; same-origin in prod, Vite proxy in dev per CONTEXT.md G8). Throws `ApiError` with `{status, message}` on non-2xx.

### `web/src/api/topics.ts`
- `listTopics({sort, limit}): Promise<TopicsListResponse>` calls `/api/topics?sort=...&limit=...`.
- `getTopic(id): Promise<TopicDetailResponse>` calls `/api/topics/{id}`.
- TypeScript types mirror the Pydantic response models from CONTEXT.md G5 + G7.

---

## Accessibility minima (non-negotiable)

- All interactive elements reachable by Tab in document order.
- `v-data-table-server` rows have `role="link"` (or wrapping `<a>`); Enter activates row navigation.
- Color contrast: Vuetify default light theme meets WCAG AA on body text; the only custom color use is source-name chips, all of which use Vuetify's preset palette colors which meet AA against light backgrounds at the `text-on-{color}` foreground Vuetify computes.
- Hover-only information (full title on truncated text, absolute timestamp on relative) MUST also be exposed via `:title` attr so screen readers and keyboard-only users get it.
- Tab order in TopicDetail: Back button → table-like metadata (read-only, skipped) → Sources list, each item → external-link icon (separate tab stop, opens in new tab with `target="_blank" rel="noopener"`).

Phase 4 does not implement full WCAG AA testing; this is the **minimum
contract** the components must respect by construction.

---

## Responsive behavior

- Desktop-first. The operator's primary device is a laptop / desktop.
- `v-data-table-server` collapses gracefully at < 768px (Vuetify default mobile rendering); no custom mobile layout work in Phase 4.
- `TopicDetail.vue` uses single-column flow; mobile usable but not optimized.
- No PWA, no offline support, no install prompt.

---

## What this contract does NOT cover

- Frontend test framework / Vitest setup (deferred per CONTEXT.md)
- Skeleton loaders (table is short; `v-progress-linear` is enough)
- Dark mode toggle (Phase 5+ if requested)
- i18n (English only)
- Crawl-config UI (Phase 5)
- Business-case display (Phase 6+)
- Charts / sparklines (not in UI-002 scope)
- Filter UI (Phase 5+; CONTEXT.md G5 explicitly defers filters)
- Per-source enable/disable controls (Phase 5, UI-004)
- Routing transitions / animations (Vuetify defaults are fine)

---

## Checker Sign-Off

Inline self-check against the 6 GSD UI dimensions. (Real `gsd-ui-checker`
subagent is unavailable in this env; criteria applied manually below.)

### Dimension 1 — Copywriting: PASS
- All operator-facing strings enumerated above, no `TODO` or
  placeholder copy in the spec.
- Empty/loading/error/404 states each have a concrete heading + body
  with a next-step action (e.g., "check scheduler is running").
- No marketing tone; no emoji; operator-internal voice consistent.
- No destructive actions in Phase 4 → "destructive confirmation: N/A"
  is the correct value, not a missing field.

### Dimension 2 — Visuals: PASS
- Every screen has a named root component and explicit Vuetify
  primitives (`v-app`, `v-app-bar`, `v-card`, `v-data-table-server`,
  `v-list`, `v-alert`, `v-progress-linear`).
- States enumerated for both screens: loaded, loading, error, empty
  (list); loaded, loading, error, 404 (detail).
- Affordance for "row is clickable" is explicit: cursor pointer + accent
  hover tint + whole-row click (no easy-to-miss tiny chevron icon).
- Truncation rule explicit: description 100 chars, detail title 80 chars,
  both with hover-full via `:title` attr.

### Dimension 3 — Color: PASS
- 60/30/10 ratios assigned to concrete Vuetify tokens (`surface` 60%,
  `background`/`on-surface` 30%, `primary` 10%).
- Accent has an **explicit reserved list of 4 items** — not "all
  interactive elements" (which is the documented anti-pattern).
- Items specifically excluded from accent are also enumerated to
  prevent the "everything is blue" creep.
- Error color reserved for error state only; success/warn unused in
  Phase 4 (intentional — read-only views).

### Dimension 4 — Typography: PASS
- 4 type roles assigned (body, label, heading, display), each mapped to
  a Vuetify utility class.
- Sizes 14 / 12 / 20 / 24 px — concrete, not "small/medium/large".
- Single font family (Roboto, self-hosted) — no font sprawl.
- Phase 4 weights limited to Vuetify-preset {400, 500} — no custom
  weight introduction.

### Dimension 5 — Spacing: PASS
- 7 tokens declared (xs..3xl), all multiples of 4 ✓.
- Each token mapped to a concrete Vuetify utility class (`*-1`..`*-16`).
- Per-screen usage documented (page container = `*-8`, card padding =
  `*-4`, section break = `*-12`).
- No magic numbers in component contracts (all spacing via Vuetify
  utility classes).

### Dimension 6 — Registry Safety: PASS
- Only registries: Vuetify official + Material Design Icons. Both
  first-party, MIT, no third-party blocks → no safety gate required
  per template rule.
- Explicit "no shadcn-vue, no HeadlessUI, no Quasar" anti-decision is
  recorded — prevents accidental sprawl in Phase 5+ work.

**Approval:** approved 2026-05-16 (inline checker; no `gsd-ui-checker`
subagent available in this env, but all 6 dimensions checked against
the same criteria the subagent enforces).
