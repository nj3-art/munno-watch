# CineZone Architecture

## Current structure

The project is midway through an incremental Flask refactor. Existing templates and assets stay in place to preserve the UI and URL behavior.

```text
backend/
  app/
    __init__.py     # create_app; registers extensions and Blueprints
    config.py       # environment-based configuration
    extensions.py   # shared Flask-WTF CSRF extension
    database.py     # request-scoped SQLite connection lifecycle
    auth.py         # session user lookup, authorization decorators, redirect validation
    routes.py       # main Blueprint, legacy SQLite schema/seed setup, catalog queries, views
  __init__.py
cinezone.py         # compatibility and local development entry point
templates/
static/
tests/
```

`create_app()` constructs a Flask instance, configures the existing root-level `templates/` and `static/` directories, applies configuration overrides, initializes CSRF protection, and registers the `main` Blueprint. Template endpoint references use the `main.` namespace. Existing public URLs are unchanged.

The current runtime database layer is still SQLite and uses direct parameterized SQL. It is not SQLAlchemy and does not provide production MySQL support yet. The local SQLite database remains a separate ignored file and has not been migrated or overwritten.

## Request/data flow today

1. `cinezone.py` imports `create_app()` and exports `app` for compatibility.
2. The factory loads `backend/app/config.py`, initializes CSRF protection, installs database cleanup, and registers `main`.
3. Route handlers use `backend/app/auth.py` for session and permission checks and `backend/app/database.py` for a request-scoped SQLite connection.
4. The route handlers query local catalog records and render the existing templates.

## Target boundaries

Continue separating responsibilities without changing behavior gratuitously:

- **Configuration/extensions:** app settings, CSRF, migration, and ORM extension objects.
- **Models/database:** SQLAlchemy models, relationship constraints, migration setup, and legacy SQLite import tooling.
- **Authentication:** user/role lookup, access checks, sessions, and account services.
- **Routes/Blueprints:** focused page, authentication, catalog, and admin endpoints.
- **Services:** metadata provider, storage, media authorization, email, and advertising adapters.
- **Templates/static:** presentation only; no secrets or provider credentials.

## Target database flow

The intended production data path is Flask-SQLAlchemy to a managed MySQL service via an environment-provided database URL. Alembic/Flask-Migrate owns schema changes. The existing ignored `cinezone.db` must be backed up and imported through a repeatable migration tool; it must not be deleted or used as the production database. Development/test environments should be isolated from production data.

## External service boundaries

Cloud storage, metadata, email, advertising, and video delivery should be accessed through server-side service adapters. Credentials belong in local environment configuration or provider dashboards, never templates or Git. An adapter is not considered operational until configured and verified against its provider.

## Current architectural limitations

- SQLite schema creation, sample seed data, catalog queries, and multiple route groups still share `backend/app/routes.py`.
- There are no SQLAlchemy models, migrations, service adapters, or production WSGI server.
- There is no API versioning; existing routes are server-rendered HTML.
- No hosting or external service has been configured.
