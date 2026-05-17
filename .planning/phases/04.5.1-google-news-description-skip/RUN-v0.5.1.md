# Run v0.5.1 Deploy Gate

**Tag:** `v0.5.1` (commit `a26ebc0`)
**Phase:** 4.5.1 — Google News description skip + one-shot cleanup of dirty rows
**Prereq:** operator at terminal with `gcloud auth login` active + project set

---

## Step 1 — Build + deploy

```bash
gcloud builds submit \
  --config=cloudbuild.yaml \
  --region=europe-west2 \
  --substitutions=TAG_NAME=v0.5.1,COMMIT_SHA=$(git rev-parse --short HEAD)
```

**Expected:** build → push → deploy succeeds, Cloud Run revision serves
`BUILD_VERSION=v0.5.1`. ~5-8 min.

**Sanity check after deploy:**
```bash
curl -s https://<cloud-run-url>/healthz
# expect: {"status":"ok","version":"v0.5.1",...}
```

---

## Step 2 — Clear dirty Google-News-only descriptions in prod

Same pattern as Phase 4.5 backfill — operator runs the script locally
against the prod DSN:

```bash
DATABASE_URL="<prod-dsn-postgresql+asyncpg-url>" \
  uv run python scripts/clear_google_news_descriptions.py --dry-run
```

**Expected dry-run output:**
```
would NULL ~29 google-news-only topic descriptions
```
(Local docker DB reported 27 at time of plan; prod may be ±2 depending on
whether the 12h crawler ran again between v0.5.0 and v0.5.1 — both numbers
are fine.)

Then drop `--dry-run`:

```bash
DATABASE_URL="<prod-dsn-postgresql+asyncpg-url>" \
  uv run python scripts/clear_google_news_descriptions.py
```

**Expected:** `NULLed N google-news-only topic descriptions` (same N as
dry-run).

**Idempotency proof:**
```bash
DATABASE_URL="<prod-dsn-postgresql+asyncpg-url>" \
  uv run python scripts/clear_google_news_descriptions.py
# expect: NULLed 0 google-news-only topic descriptions
```

---

## Step 3 — Eyeball the SPA

Open the prod Cloud Run URL. Verify:

- [ ] **Google-News-only topics:** card subtitle is empty, detail paragraph
      is empty (the `<ol><li><a>` HTML link-list is gone)
- [ ] **NYT topics:** subtitle + detail paragraph **still present** with
      publisher prose unchanged
- [ ] **Cross-source topics** (observed by both NYT + Google News): NYT
      prose still showing (the first-non-empty merge preserved it; cleanup
      script excluded these by design via the `NOT EXISTS non-google_news`
      predicate)
- [ ] **HN topics:** unchanged (HN feed has no `<description>` by design;
      none of this plan touched HN)
- [ ] Resolved URLs still click through correctly on NYT cards

---

## Acceptance

Plan 04.5.1 = done when all of:
- [ ] Step 1 deploy reports SUCCESS, `/healthz` shows v0.5.1
- [ ] Step 2 dry-run + real run + re-run sequence matches expected output
- [ ] Step 3 checklist all green

---

## What's next

After this gate closes, the next workflow is the **login page** (per
operator decision m1276 + m1278). That ships as its own GSD workflow
(`/gsd-quick` recommended, Minimal scope: 1 shared user/password in Secret
Manager + signed-cookie session). v0.5.1 is the LAST unauthenticated
deploy.
