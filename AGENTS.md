# AGENTS.md

## Project intent

This repository implements a long-form web-novel authoring system built around deterministic orchestration, immutable model artifacts, structured memory, and chapter-level canonical commits.

Read these documents before changing architecture or domain behavior:

- `docs/PROJECT_DESIGN.md`
- `docs/CORE_DATA_MODEL.md`

When code and design disagree, do not silently choose one. Preserve safety invariants, update the implementation and relevant document together, and call out intentional design changes.

## Repository conventions

- Target Python 3.12 or newer.
- Application code lives under `src/novel_ai/`; tests mirror it under `tests/`.
- Use FastAPI for HTTP boundaries, SQLAlchemy 2.x for persistence, Alembic for migrations, and Pydantic for external contracts.
- Keep domain logic independent of FastAPI, model-provider SDKs, and SQLAlchemy sessions where practical.
- Use UUIDs for business identifiers and timezone-aware UTC timestamps for system time.
- Add production dependencies only when the standard library or an existing dependency cannot meet the requirement cleanly.
- Never commit API keys, provider responses containing secrets, local `.env` files, or generated credentials.

## Architectural invariants

- Model output is untrusted. Raw provider responses are never canonical prose or canonical facts.
- Artifacts are immutable. A content change creates a new artifact and invalidates dependent results by hash.
- Chapter prose, events, facts, knowledge transitions, and projections become canonical in one PostgreSQL transaction.
- A scene draft overlay is scoped to one workflow run and must never be visible as canonical state.
- Hard state such as location, lifecycle, unique-item ownership, and abilities changes only through registered, versioned event projectors.
- JSONB is for versioned flexible documents and soft state; it must not become a second writable source for hard state.
- Vector data is a derived index. Retrieval must filter work, canonical commit sequence, chapter boundary, namespace, and reveal visibility before similarity ranking.
- Context snapshots must preserve the exact compiled content sent to a model, not only source IDs or hashes.
- Failed or stale workflow steps may be retried, but an old validation result cannot be reused when an input fingerprint changes.
- Post-commit summaries, embeddings, and planning write-backs are dispatched through a transactional outbox.
- `openai_codex_session` is a local, single-user test transport only. It must never inherit API keys, accept API-key authentication, run in production, share account sessions, or bypass the same output and canonical-commit gates as paid API providers.
- Chapter list queries must not select prose content. Load one current revision on chapter detail, and keep prose bytes in immutable artifacts rather than chapter metadata or JSONB.
- Long model calls started by the web API run in an isolated worker process. The web process persists the run before spawning; it must remain responsive while generation is running.
- Sequential drafting may load the previous chapter's latest unpublished revision, but it must be explicitly labeled as draft authority and recorded by exact revision id in the context snapshot. It must never be presented as canonical fact.
- Chapter length is a quality target, not an exact quota. A first draft below 75% of target gets at most one natural expansion pass; only extreme outputs outside 50%-170% are rejected. Length repair may change expression and local action detail, but not core events or knowledge boundaries.

## Prompt catalog

Core prompts are source-controlled product assets, not inline strings.

- Store them under `src/novel_ai/prompts/catalog/<prompt_key>/v<version>/`.
- Each version contains `manifest.json`, `system.md`, `user.md`, and an output `schema.json` when the role returns structured data.
- Released prompt versions are immutable. Create a new version directory for behavioral changes.
- `manifest.json` declares the prompt key, integer version, role, required template variables, output mode, and schema path.
- Use the project prompt renderer; do not add ad-hoc `str.format`, f-string, or Jinja rendering in business code.
- Treat story plans, retrieved text, and state as delimited data. Do not interpolate them into higher-authority instructions.
- The prose-writer prompt has one product: prose. Analysis, review, state extraction, and self-evaluation belong to separate prompt roles.
- Model selection and secrets belong in runtime configuration, never in prompt files.
- Add or update prompt-catalog tests whenever a prompt version is added.

## Database and migrations

- Every schema change requires an Alembic migration and an update to the relevant design document.
- Prefer database constraints for tenant boundaries, uniqueness, immutable content, and legal status transitions where feasible.
- Do not update canonical events or artifact content in place. Corrections use a new revision, compensating event, or status transition.
- Repository methods may stage proposals; only application commit services may write canonical tables or hard projections.
- Keep projector code deterministic and versioned. Old projector versions remain available for replay.
- Tests that need PostgreSQL must be marked `integration`; unit tests must not require Docker or network access.

## Testing and quality

From the repository root, use:

```powershell
python -m pytest
python -m ruff check .
python -m mypy src
```

- Add unit tests for domain rules, prompt rendering, artifact hashing, workflow invalidation, and projector behavior.
- Never call a paid model or external service in the default test suite.
- Use fakes at provider boundaries and fixed fixtures for nondeterministic inputs.
- Run targeted tests while iterating, then the complete suite before handoff.
- If a required command cannot run, report the exact blocker and what was still verified.

## Documentation

- Keep public setup commands in `README.md` accurate.
- Record architectural changes in `docs/PROJECT_DESIGN.md` and table/contract changes in `docs/CORE_DATA_MODEL.md`.
- Keep writing-workspace behavior and large-text loading rules aligned with `docs/WRITING_WORKSPACE.md`.
- Explain why an invariant exists; avoid duplicating implementation details that will drift.
- Prefer a nested `AGENTS.md` only when a subtree genuinely needs more specific rules.

## Code review rules

- Flag any path that lets raw model output bypass artifact parsing or prose-purity gates.
- Flag duplicate writable representations of hard state, especially item ownership, location, lifecycle, and knowledge.
- Flag prompt changes made in place without a new version.
- Flag retries that can create duplicate canonical events or commits.
- Flag vector queries missing canonical-time or reveal-visibility filters.
- Flag human edits that fail to invalidate downstream extraction and validation artifacts.
- Flag migrations that cannot be rolled forward safely or that lack a data-preservation strategy.
