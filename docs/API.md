# API Reference

Base URL: `/api`

## Authentication

Most endpoints require a valid session cookie (`tr_session`), set via the login endpoint. Public endpoints (no auth required): `/api/login`, `/api/logout`, `/api/healthz`. The internal crawl endpoint uses Bearer PAT auth instead of cookies.

---

## Endpoints

### GET /api/healthz

Liveness + DB reachability probe.

| Property | Value |
|----------|-------|
| Auth | No |
| Query params | None |
| Request body | None |

**Response (200):**
```json
{ "status": "ok", "db": "reachable" }
```

**Response (503):**
```json
{ "status": "degraded", "db": "unreachable" }
```

```bash
curl http://localhost:8000/api/healthz
```

---

### POST /api/login

Authenticate and receive a session cookie.

| Property | Value |
|----------|-------|
| Auth | No |
| Query params | None |

**Request body:**
```json
{ "username": "string", "password": "string" }
```

**Response (200):** Sets `tr_session` httponly cookie.
```json
{ "ok": true, "username": "alice" }
```

**Response (401):**
```json
{ "detail": "Invalid username or password" }
```

```bash
curl -X POST http://localhost:8000/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"secret"}'
```

---

### POST /api/logout

Clear the session cookie.

| Property | Value |
|----------|-------|
| Auth | No |
| Query params | None |
| Request body | None |

**Response (200):**
```json
{ "ok": true }
```

```bash
curl -X POST http://localhost:8000/api/logout
```

---

### GET /api/me

Check if current session is valid (used by SPA auth guard).

| Property | Value |
|----------|-------|
| Auth | Yes (session cookie) |
| Query params | None |
| Request body | None |

**Response (200):**
```json
{ "ok": true }
```

**Response (401):**
```json
{ "detail": "Authentication required" }
```

```bash
curl http://localhost:8000/api/me --cookie "tr_session=<token>"
```

---

### GET /api/topics

Paginated list of topics with derived stats.

| Property | Value |
|----------|-------|
| Auth | Yes (session cookie) |
| Request body | None |

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `sort` | string | `-last_seen_at` | Sort key. Allowed: `breadth`, `longevity`, `last_seen_at`. Prefix with `-` for descending. |
| `limit` | int (1-100) | `20` | Max results to return. |

**Response (200):**
```json
{
  "topics": [
    {
      "id": "uuid",
      "title": "string",
      "description": "string | null",
      "first_seen_at": "datetime",
      "last_seen_at": "datetime",
      "observation_count": 5,
      "breadth": 3,
      "longevity_seconds": 86400
    }
  ],
  "limit": 20,
  "sort": "-last_seen_at"
}
```

```bash
curl "http://localhost:8000/api/topics?sort=-breadth&limit=10" \
  --cookie "tr_session=<token>"
```

---

### GET /api/topics/{topic_id}

Full detail for one topic including sources and metadata.

| Property | Value |
|----------|-------|
| Auth | Yes (session cookie) |
| Path params | `topic_id` (UUID) |
| Query params | None |
| Request body | None |

**Response (200):**
```json
{
  "id": "uuid",
  "title": "string",
  "description": "string | null",
  "first_seen_at": "datetime",
  "last_seen_at": "datetime",
  "observation_count": 5,
  "breadth": 3,
  "longevity_seconds": 86400,
  "topic_metadata": {},
  "sources": [
    {
      "id": "uuid",
      "source_name": "hackernews",
      "url": "https://...",
      "resolved_url": "https://... | null",
      "native_rank": 1,
      "observed_at": "datetime"
    }
  ]
}
```

**Response (404):**
```json
{ "detail": "Topic <id> not found" }
```

```bash
curl http://localhost:8000/api/topics/550e8400-e29b-41d4-a716-446655440000 \
  --cookie "tr_session=<token>"
```

---

### GET /api/runs

Recent crawl runs, newest first.

| Property | Value |
|----------|-------|
| Auth | Yes (session cookie) |
| Request body | None |

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int (1-100) | `20` | Max runs to return. |

**Response (200):**
```json
{
  "runs": [
    {
      "id": "uuid",
      "started_at": "datetime",
      "finished_at": "datetime",
      "duration_ms": 12345,
      "top_n": 100,
      "totals_fetched": 500,
      "totals_inserted": 42,
      "totals_updated": 18,
      "totals_skipped_within_run": 440,
      "totals_errors": 0,
      "per_source": { "hackernews": { "fetched": 100, "inserted": 10, "updated": 5, "skipped_within_run": 85, "errors": 0 } },
      "failed_sources": []
    }
  ],
  "limit": 20
}
```

```bash
curl "http://localhost:8000/api/runs?limit=5" --cookie "tr_session=<token>"
```

---

### GET /api/crawl-config

List all crawl source configurations.

| Property | Value |
|----------|-------|
| Auth | Yes (session cookie) |
| Query params | None |
| Request body | None |

**Response (200):**
```json
[
  {
    "source_name": "hackernews",
    "enabled": true,
    "top_n": 100,
    "capture_summary": false,
    "feed_url": null,
    "updated_at": "datetime"
  }
]
```

```bash
curl http://localhost:8000/api/crawl-config --cookie "tr_session=<token>"
```

---

### PUT /api/crawl-config/{source_name}

Update mutable fields for one crawl source.

| Property | Value |
|----------|-------|
| Auth | Yes (session cookie) |
| Path params | `source_name` (string) |
| Query params | None |

**Request body** (all fields optional, at least one required):
```json
{ "enabled": true, "top_n": 50 }
```

- `enabled`: bool | null
- `top_n`: int (1-500) | null

**Response (200):**
```json
{
  "source_name": "hackernews",
  "enabled": true,
  "top_n": 50,
  "capture_summary": false,
  "feed_url": null,
  "updated_at": "datetime"
}
```

**Response (400):** `{ "detail": "No fields to update" }`
**Response (404):** `{ "detail": "Source '<name>' not found" }`

```bash
curl -X PUT http://localhost:8000/api/crawl-config/hackernews \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}' \
  --cookie "tr_session=<token>"
```

---

### POST /api/internal/crawl

Trigger a synchronous crawl run. Intended for Cloud Scheduler.

| Property | Value |
|----------|-------|
| Auth | Yes (Bearer PAT via `TREND_INTERNAL_PAT` env var) |
| Query params | None |
| Request body | None |

**Response (200):**
```json
{
  "status": "ok",
  "crawl_run_id": "uuid",
  "totals": { "fetched": 500, "inserted": 42, "updated": 18, "skipped_within_run": 440, "errors": 0 }
}
```

**Response (500):**
```json
{ "detail": "crawl failed: <error message>" }
```

```bash
curl -X POST http://localhost:8000/api/internal/crawl \
  -H "Authorization: Bearer <PAT_TOKEN>"
```
