# CineZone Project Audit

**Audit date:** 2026-11-15  
**Scope:** Current workspace. No external hosting, database, or storage account was accessed.

## Executive summary

CineZone is a small Flask application with a coherent dark streaming-service design, local SQLite catalog, basic account flows, watchlists, and an admin feature-selection page. Its existing pages render successfully in local tests. Recent provider-independent hardening added CSRF protection, safer redirects, registration and filter validation, secure production cookie settings, and security headers.

It is **not yet production-deployable**. There is no production WSGI server/configuration, health endpoint, ORM, migration history, production database, object storage, protected media delivery, download system, or external service configuration. The current movie media references are sample URLs and do not demonstrate authorized streaming.

The target database is MySQL, as specified by the project owner. The MySQL hosting provider remains undecided. No paid services, hosting accounts, credentials, or deployment were created or verified.

## Current architecture and workspace

The application has begun an incremental refactor into a Flask package. The existing templates and static assets remain at the repository root:

```text
.
├── cinezone.py
├── backend/
│   ├── __init__.py
│   └── app/
│       ├── __init__.py
│       ├── auth.py
│       ├── config.py
│       ├── database.py
│       ├── extensions.py
│       └── routes.py
├── requirements.txt
├── .gitignore
├── templates/
│   ├── admin.html
│   ├── base.html
│   ├── index.html
│   ├── login.html
│   ├── movie.html
│   ├── movies.html
│   ├── profile.html
│   ├── register.html
│   └── watch.html
├── static/
│   ├── css/style.css
│   └── js/main.js
└── tests/
    └── test_app.py
```

The workspace also contains an ignored local `cinezone.db` and generated Python cache files. The SQLite database is not tracked by Git and was not modified during this audit. At inspection it contained 10 sample movies, one pre-existing admin account, an empty watchlist, and one setting.

`cinezone.py` remains a compatibility/development entry point. `backend.app.create_app()` creates the Flask app, loads configuration, initializes CSRF protection, and registers the `main` Blueprint. Template and static paths are configured to preserve the existing root-level assets.

### Backend and routes

`backend/app/routes.py` contains the `main` Blueprint, SQLite schema/seed initialization, shared catalog queries, and route handlers. `backend/app/database.py` owns request-scoped SQLite connections; `backend/app/auth.py` owns current-user lookup, access decorators, watchlist lookup, and redirect-target validation.

- `/`: homepage sections and featured movie.
- `/movies`: search, genre/year/language/rating/availability filters, and sorting.
- `/genre/<genre_name>`: genre browsing.
- `/movie/<movie_id>`: detail and related movies.
- `/watch/<movie_id>`: HTML5 player page.
- `/register`, `/login`, `/logout`: basic account flows.
- `/profile`, `/toggle-watchlist/<movie_id>`: profile and watchlist.
- `/admin`: featured-movie setting, restricted to admins.

There is no `/health` endpoint. The factory, configuration, CSRF extension, database-connection, and authentication modules are in place. The route module still combines catalog/schema initialization and multiple route groups; further extraction is part of the architecture phase.

### Dependencies

`requirements.txt` contains Flask, Flask-WTF, and Werkzeug. Flask-WTF is used for CSRF protection; Werkzeug is used for password hashing. SQLite and `unittest` come from Python's standard library. Gunicorn, SQLAlchemy, Flask-Migrate/Alembic, a MySQL driver, storage SDKs, and rate-limiting dependencies are not present.

## Existing functionality and verification

### Completed and verified locally

- Python syntax compilation succeeded for the app and tests.
- All 10 tests in `tests/test_app.py` pass after adding route-path and method preservation coverage.
- Test coverage verifies app factory registration, existing page rendering, route paths and methods, registration password validation, CSRF rejection, local versus external login redirect handling, admin route restriction, selected security headers, and malformed year/rating filters.
- A production-mode configuration check verified that debug is disabled, secure cookie flags are enabled, and import fails if `SECRET_KEY` is absent.
- `.gitignore` excludes environment files and local database files.

These are local checks only. They do not establish that Render, MySQL, cloud storage, or a public site is operational.

### Partially implemented

- Homepage sections query the SQLite catalog, but seed content is synthetic and some featured collections are hardcoded.
- Search covers title, genre, description, keywords, and director. Language and year can be filtered, not searched as free-text.
- Filtering and sorting exist, but there is no pagination, suggestions, recently-added filter, or popularity filter control.
- Movie pages display basic metadata and related titles. Release date, runtime, cast, multiple genres, and licensed-content records are absent.
- Registration, login, logout, hashed passwords, admin checks, and watchlists exist. Profile editing, password recovery/change, verification, favourites, and watch history do not.
- The admin page can change the featured movie only. It cannot manage catalog entries, users, roles, uploads, rights, or site settings.
- The player has standard browser controls but uses public sample MP4 URLs. There is no secure source resolution, authorization, range-serving implementation, subtitle/quality selection, download, or playback-progress persistence.
- CSS includes responsive breakpoints, but there is no interactive mobile navigation or automated cross-device/browser testing.

## Findings and priority

### Critical before production

1. **Persistent data:** Local SQLite is not a suitable multi-instance production database. Implement SQLAlchemy models, MySQL connection configuration, migrations, and a tested import strategy before switching providers. Preserve and assess `cinezone.db`; do not delete it.
2. **Application serving:** The current entry point uses Flask's development server. Add a WSGI entry point and production server, production configuration, logging, and health check.
3. **Credentials:** Production must receive a strong secret from environment configuration. A prior local database may still contain the original demo admin account; the recent code change prevents a fixed-password admin from being seeded into a new database, but does not alter the existing local database.
4. **Media rights and access:** Current demo URLs are not a licensed catalog. Do not publish or enable streaming/downloads until the owner has recorded distribution rights and configured private media storage and delivery.
5. **External configuration:** Hosting, MySQL, object storage, custom domain, and HTTPS must be configured and verified in their respective accounts. None is configured by this repository audit.

### Important functionality and architecture gaps

- `backend/app/routes.py` is still large and mixes SQLite schema/seed setup, catalog queries, and route groups. The app factory, Blueprint, database connection, and auth modules are verified; further separation remains.
- SQLite tables do not define foreign keys or user/movie relationships at the database level. There is no schema versioning or migration workflow.
- Discovery lacks pagination and several requested filters. The detail page lacks TMDB integration and extended metadata.
- No movie CRUD, publication/rights management, upload/download, user administration, or durable audit log.
- No watch history, favourites, continue-watching, password recovery, or email verification.
- No ads/AdSense integration, analytics, privacy/consent handling, legal pages, sitemap, robots.txt, or backup/recovery procedure.
- The CSS uses remote image/font resources. Images are not optimized or lazy-loaded; the catalog is loaded without pagination.
- There is no README, API/database/security/deployment documentation, CI workflow, or tests for migrations, storage, downloads, uploads, or browser responsiveness.

## Recommended implementation sequence

1. **Finish the architecture phase:** extract database and authentication responsibilities from the large routes module; preserve behavior with regression tests.
2. **MySQL persistence:** add SQLAlchemy models and relationships for currently functional features first, then add a migration/import path from SQLite. Add only schema needed for near-term features; expand entities with their actual workflows.
3. **Production runtime:** add a WSGI entry point, Gunicorn, logging, a health endpoint, and deployment configuration. Configure database URL through secrets/environment variables.
4. **Discovery and metadata:** add pagination, complete filters, TMDB integration with attribution and terms review, and extend movie details.
5. **Account and admin workflows:** add profile/watch history/favourites as scoped features; implement admin CRUD and roles with authorization tests.
6. **Rights and media delivery:** model rights and access permissions; integrate S3-compatible private storage, validated admin uploads, expiring playback/download links, and activity logs. Verify Range support. Assess HLS/transcoding only when required by actual video sizes and audience.
7. **Monetization and compliance:** add configurable ad placements and legitimate analytics without fabricated metrics; prepare consent, privacy, terms, copyright/takedown, and payment-provider documentation.
8. **Quality and operations:** add cross-device browser checks, SEO metadata, caching, backups/recovery, CI, deployment documentation, and end-to-end verification.

Do not claim an external integration is complete until its account configuration and live behavior have been verified. No paid service should be activated without the owner's approval.

## Changes since initial baseline

- Added `backend/app` with an application factory, environment configuration, CSRF extension initialization, and the `main` Blueprint.
- Extracted request-scoped database connections and authentication helpers into separate modules.
- Kept `cinezone.py` as the existing development/compatibility entry point and preserved the route URLs.
- Updated template endpoint references for Blueprint routing.
- Added a factory regression test; all 9 tests pass locally.
