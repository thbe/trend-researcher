# crawler

Stage 1 ingest service. Deterministic, zero AI.

Layout (ports & adapters):

- **`domain/`** — Pure value objects and dedup logic. No I/O, no SQLAlchemy, no httpx.
- **`ports/`** — Protocols / ABCs that the app layer depends on (`SourcePort`, `TopicRepositoryPort`).
- **`adapters/`** — Concrete I/O implementations of the ports (`adapters/sources/` for crawlers, `adapters/persistence/` for the Postgres repository).
- **`app/`** — Composition root, orchestrator, and Typer CLI entrypoint.
