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
- Extract CSRF, database initialization, and authentication helpers.
- Preserve `cinezone.py` as a compatibility/development entry point.
- Extract SQLite schema/seed setup and split route groups into focused modules.
- Keep templates and static assets in their existing locations until tested references are updated.

**Acceptance:** the app factory and CLI entry point render existing pages; focused tests pass.

## Phase 3 — SQLAlchemy, MySQL, and migration

**Status: IN PROGRESS**

- [x] Add SQLAlchemy/Flask-SQLAlchemy and Flask-Migrate/Alembic.
- [x] Model current users, movies, settings, and watchlists with foreign keys and uniqueness constraints.
- [x] Configure production MySQL URLs through `DATABASE_URL`; retain SQLite for local development/tests.
- [x] Add an initial migration and an explicit, transactional SQLite import path for an empty target.
- [x] Use a separate `cinezone-dev.db` by default so local schema initialization does not alter the legacy database.
- [ ] Configure and verify a live MySQL provider; do not activate or pay for a service without approval.
- [ ] Test import against a backup of the actual local database after owner review; never alter or delete the source.
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

- [x] Add server-side pagination to movie and genre listings, preserving query filters.
- [x] Reject invalid page and sort values; keep rights-aware query results.
- [ ] Complete validated search/filter controls, suggestions, recent/popularity filters, and admin-managed genres.
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

- [x] Add protected movie create/edit/unpublish workflows and publication/search filters.
- [x] Add rights metadata, verified-rights attestation, upload status, and a recent user list.
- [x] Record and display administrator creation, movie create/update/unpublish, and featured-movie changes.
- [ ] Add genre CRUD, role/permission management, user management, and complete audit coverage/retention.
- [ ] Add dashboards only from real stored data.

## Phase 8 — Rights and media delivery

**Status: TESTED — PASS (local implementation)**

- [x] Store rights holder, licence reference, territories, permissions, dates, and publication state separately from legacy movie columns.
- [x] Add admin-only upload handling and private local storage with extension, MIME, signature, and size validation.
- [x] Gate publication, watch, stream, poster, trailer, download, genre, and watchlist paths on current rights.
- [x] Add local range streaming and an optional S3-compatible signed-URL adapter.
- [ ] Verify byte-range seeking with actual licensed media and a configured provider; browser testing remains.
- [ ] Add geographic rights enforcement and entitlements; current conservative behavior restricts non-worldwide and non-free playback to admins.
- [ ] Add media activity logging. HLS/transcoding remains conditional on real media requirements.

**External boundary:** storage/CDN credentials and any media-processing account remain owner-managed and may incur storage, request, processing, and bandwidth costs.
The S3 adapter is not provider-tested; local tests use a tiny synthetic file-signature fixture and do not establish real playback or distribution rights.

## Phase 9 — Monetization and analytics

**Status: NOT STARTED**

- Build configurable ad placements and legitimate direct-ad records.
- Research current AdSense eligibility/policy and Uganda payout options from official sources before advising activation.
- Keep payment records informational; never collect payment credentials or fabricate performance metrics.
- Add privacy/consent handling before analytics or advertising identifiers.

## Phase 10 — Security

**Status: IN PROGRESS**

- [x] Retain CSRF, password, redirect, cookie, and security-header protections.
- [x] Add upload validation, generated storage keys, private files, and media authorization regression tests.
- [ ] Add rate limits, broader production error handling review, dependency review, and external security testing.

## Phase 11 — Testing and QA

**Status: IN PROGRESS**

- [x] Keep automated tests and migration checks isolated from `cinezone.db`.
- [x] Add route, authorization, publication, upload, range, download, S3-missing-configuration, health, and legacy-import tests.
- [x] Verify additive migrations on disposable SQLite and generate offline MySQL DDL.
- [ ] Add browser/mobile tests, real-media/provider integration tests, and production-like deployment checks.
- Current local result: 30 unittest cases pass; this does not verify external services.

## Phase 12 — SEO and performance

**Status: NOT STARTED**

- Add unique metadata, canonical URLs, sitemap, robots rules, and truthful structured data.
- Add indexes, lazy-loaded/optimized images, caching, and measured asset optimization.
- Measure before introducing additional infrastructure.

## Phase 13 — Deployment

**Status: IN PROGRESS**

- [x] Add WSGI/Gunicorn entry point, health endpoint, environment example, and deployment guide.
- [ ] Select and configure a hosting provider and MySQL database with owner approval; no service is provisioned.
- [ ] Configure HTTPS/domain, backups, logging, monitoring, and test the actual deployment before claiming the site is live.

## Phase 14 — Business readiness

**Status: NOT STARTED**

- Add configurable legal/contact pages and content removal workflow; identify text that needs qualified legal review.
- Document backup/restore and maintenance without running destructive restores.
- Verify content rights, advertising approval, payment requirements, and external-service limits before launch.

## Documentation deliverables

Maintain `PROJECT_AUDIT.md`, `PROJECT_PROGRESS.md`, `DEVELOPMENT_ROADMAP.md`, `ARCHITECTURE.md`, and `DEPLOYMENT_GUIDE.md` as workflows evolve. Add database, security, backup, API, and third-party-service documentation alongside those features. Distinguish local tests from externally verified behavior.
