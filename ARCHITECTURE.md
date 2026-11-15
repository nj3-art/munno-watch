# CineZone Architecture

## Current structure

The project is midway through an incremental Flask refactor. Existing templates and assets stay in place to preserve the UI and URL behavior.

```text
backend/
  app/
    __init__.py     # create_app; registers extensions and Blueprints
    config.py       # environment-based configuration
    extensions.py   # CSRF, SQLAlchemy, and Flask-Migrate extensions
    database.py     # non-production schema initialization
    models.py       # SQLAlchemy entities and safe legacy SQLite import
    auth.py         # session user lookup, authorization decorators, redirect validation
    routes.py       # main Blueprint and ORM-backed page handlers
  migrations/       # Alembic schema revisions
  __init__.py
cinezone.py         # compatibility and local development entry point
templates/
static/
tests/
```

`create_app()` constructs a Flask instance, configures the existing root-level `templates/` and `static/` directories, applies configuration overrides, initializes CSRF, SQLAlchemy, and Flask-Migrate, and registers the `main` Blueprint. Template endpoint references use the `main.` namespace. Existing public URLs are unchanged.

SQLAlchemy models now back the current routes. `DATABASE_URL` selects the database; production requires a `mysql+pymysql://` URL, while local development defaults to the ignored `cinezone.db`. The local SQLite database remains untouched. `flask db upgrade` applies schema migrations; the explicit `import-legacy-sqlite` command copies records into a separately migrated empty target database.

## Request/data flow today

1. `cinezone.py` imports `create_app()` and exports `app` for compatibility.
2. The factory loads `backend/app/config.py`, initializes CSRF/SQLAlchemy/migrations, and registers `main`.
3. Route handlers use `backend/app/auth.py` for session and permission checks and SQLAlchemy models for persistent data.
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

The intended production data path is Flask-SQLAlchemy to a managed MySQL service via an environment-provided database URL. Alembic/Flask-Migrate owns schema changes. The existing ignored `cinezone.db` must be backed up and imported through the explicit transactional command; it must not be deleted or used as the production database. The importer requires an empty destination, reads the source in SQLite read-only mode, preserves IDs and relationships, and removes known sample playback URLs from imported records. Development/test environments should be isolated from production data.

## External service boundaries

Cloud storage, metadata, email, advertising, and video delivery should be accessed through server-side service adapters. Credentials belong in local environment configuration or provider dashboards, never templates or Git. An adapter is not considered operational until configured and verified against its provider.

## Current architectural limitations

- Multiple route groups still share `backend/app/routes.py`.
- Live MySQL connectivity and a production WSGI server have not been configured or verified.
- The legacy SQLite schema is not retrofitted with migration constraints; use a separate empty destination for import.
- There is no API versioning; existing routes are server-rendered HTML.
- No hosting or external service has been configured.
