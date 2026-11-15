# CineZone Development Roadmap

This roadmap is based on the verified current implementation in `PROJECT_AUDIT.md`. Work proceeds in small phases, preserving existing route behavior and the CineZone visual identity. A feature is marked tested only after its behavior is executed.

## Phase 1 — Audit and checkpoint

**Status: TESTED — PASS**

- Inventory existing source, templates, styles, JavaScript, database, tests, and Git state.
- Record working behavior and gaps in `PROJECT_AUDIT.md` and `PROJECT_PROGRESS.md`.
- Start from the clean pushed checkpoint `a99866e`.

## Phase 2 — Architecture

**Status: IN PROGRESS**

- Introduce a Flask application factory and configuration module.
- Register current routes through a Blueprint without changing their public paths.
- Extract CSRF initialization, request-scoped database connections, and authentication helpers.
- Preserve `cinezone.py` as a compatibility/development entry point.
- Extract SQLite schema/seed setup and split route groups into focused modules.
- Keep templates and static assets in their existing locations until tested references are updated.

**Acceptance:** the app factory and CLI entry point render existing pages; focused tests pass.

## Phase 3 — SQLAlchemy, MySQL, and migration

**Status: NOT STARTED**

- Add SQLAlchemy/Flask-SQLAlchemy and Flask-Migrate/Alembic.
- Model current users, movies, settings, and watchlists with foreign keys, constraints, and indexes.
- Configure a MySQL URL exclusively through environment variables; retain SQLite for local tests/development as appropriate.
- Add migrations and seed only clearly identified sample data.
- Write and test a repeatable SQLite export/import path. Back up the current ignored database before any migration; never delete it.
- Expand the schema only alongside functional features (roles, rights, watch history, etc.).

**External boundary:** an owner-selected managed MySQL provider and credentials are required for a live connection. Do not provision or pay for a service without approval.

## Phase 4 — Frontend

**Status: IN PROGRESS**

- Preserve the established dark navy/purple design.
- Fix and verify mobile navigation, accessibility, loading, empty, and error states.
- Ensure all visible controls navigate or submit real operations.
- Add automated responsive checks where tooling is available.

## Phase 5 — Movie discovery and metadata

**Status: IN PROGRESS**

- Add pagination and complete validated search, filtering, and sorting.
- Add related collections and movie details from persistent database records.
- Research the current TMDB API terms/attribution before adding a review-before-import workflow.
- Do not infer distribution rights from metadata or posters.

## Phase 6 — User accounts

**Status: IN PROGRESS**

- Add profile editing, account status, password change/recovery, and optional email verification.
- Add favourites, watch history, recently viewed, and continue-watching progress.
- Rate-limit sensitive endpoints and verify strict user ownership in tests.
- Integrate email only after a provider is configured; report unconfigured delivery honestly.

## Phase 7 — Administration

**Status: IN PROGRESS**

- Add protected movie/genre CRUD, publication, and homepage configuration.
- Add role/permission and user management with server-side authorization.
- Add audit logging and dashboards only from real stored data.

## Phase 8 — Rights and media delivery

**Status: NOT STARTED**

- Store rights holder, licence reference, territories, permissions, dates, and restrictions.
- Define a private S3-compatible storage interface and admin-only validated uploads.
- Implement expiring playback/download access, activity logging, and missing-object handling.
- Verify byte-range seeking with a configured provider. Add HLS/transcoding only when justified by real source files and audience requirements.
- Use only content the owner is authorized to distribute; no sample URL is treated as production media.

**External boundary:** storage/CDN credentials and any media-processing account remain owner-managed and may incur storage, request, processing, and bandwidth costs.

## Phase 9 — Monetization and analytics

**Status: NOT STARTED**

- Build configurable ad placements and legitimate direct-ad records.
- Research current AdSense eligibility/policy and Uganda payout options from official sources before advising activation.
- Keep payment records informational; never collect payment credentials or fabricate performance metrics.
- Add privacy/consent handling before analytics or advertising identifiers.

## Phase 10 — Security

**Status: IN PROGRESS**

- Extend current CSRF, password, redirect, cookie, and header protections.
- Add rate limits, secure upload handling, authorization tests, and safe production error behavior.
- Review dependencies and configuration for production.

## Phase 11 — Testing and QA

**Status: IN PROGRESS**

- Keep the test database isolated from the local user database.
- Add unit/integration tests for database migrations, permissions, media authorization, and upload/download behavior.
- Add browser/mobile tests and production-like startup checks where available.
- Run all relevant tests after each phase and record exact counts and limitations.

## Phase 12 — SEO and performance

**Status: NOT STARTED**

- Add unique metadata, canonical URLs, sitemap, robots rules, and truthful structured data.
- Use database pagination, indexes, lazy-loaded/optimized images, caching, and measured asset optimization.
- Measure before introducing additional infrastructure.

## Phase 13 — Deployment

**Status: NOT STARTED**

- Add production WSGI/Gunicorn, health checks, logging, environment examples, and Render deployment configuration.
- Document provider setup, HTTPS, domain configuration, backups, and monitoring.
- Verify an actual deployment before claiming the site is live.

## Phase 14 — Business readiness

**Status: NOT STARTED**

- Add configurable legal/contact pages and content removal workflow; identify text that needs qualified legal review.
- Document backup/restore and maintenance without running destructive restores.
- Verify content rights, advertising approval, payment requirements, and external-service limits before launch.

## Documentation deliverables

Maintain `README.md`, `PROJECT_AUDIT.md`, `PROJECT_PROGRESS.md`, `DEVELOPMENT_ROADMAP.md`, `ARCHITECTURE.md`, `DATABASE_DOCUMENTATION.md`, `API_DOCUMENTATION.md`, `SECURITY_CHECKLIST.md`, `DEPLOYMENT_GUIDE.md`, `BACKUP_AND_RECOVERY.md`, `ENVIRONMENT_SETUP.md`, and `THIRD_PARTY_SERVICES.md` as the corresponding features and workflows are implemented. Documentation must distinguish local tests from externally verified behavior.
