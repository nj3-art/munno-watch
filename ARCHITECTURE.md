# CineZone Architecture

## Current structure

The project is midway through an incremental Flask refactor. Existing templates and assets stay in place to preserve the UI and URL behavior.

```text
backend/
  app/
    __init__.py     # app factory and extension initialization
    auth.py         # session lookup, permissions, redirect validation
    commands.py     # interactive administrator setup
    config.py       # environment-based configuration
    database.py     # non-production schema initialization
    extensions.py   # CSRF, SQLAlchemy, Flask-Migrate
    models.py       # catalog, rights, assets, views, users, watchlists
    routes.py       # current main Blueprint and page/media/admin routes
    storage.py      # validated local and optional S3-compatible storage
  migrations/       # Alembic schema revisions
cinezone.py         # compatibility and local development entry point
wsgi.py             # production WSGI export
Procfile            # Gunicorn runtime command
templates/
static/
tests/
```

`create_app()` configures the existing root-level `templates/` and `static/` directories, initializes CSRF/SQLAlchemy/Flask-Migrate, and registers the `main` Blueprint. Existing public URLs remain in place.

`DATABASE_URL` selects the database; production requires a `mysql+pymysql://` URL. Local development defaults to the ignored `cinezone.db`. The additive rights/media migration adds separate tables and does not alter legacy movie columns. The local SQLite database was not modified. See `migrations/README` before applying any migration to an existing legacy database.

## Request/data flow

1. `cinezone.py` preserves the development/compatibility entry point; `wsgi.py` exports the production app.
2. The factory loads configuration, initializes CSRF/SQLAlchemy/migrations, and registers the `main` Blueprint.
3. Route handlers use `backend/app/auth.py` for account and administrator checks and SQLAlchemy models for persistent records.
4. Public queries enforce publication and active, verified rights.
5. Media routes enforce streaming/download permission, available territory restrictions, and availability rules.
6. `backend/app/storage.py` stores local uploads outside `static/` or produces short-lived S3-compatible signed URLs.
7. `/health` performs a database connectivity check for runtime monitoring.

## Responsibility boundaries and gaps

- **Configuration/extensions:** app settings, CSRF, migrations, and ORM extension objects.
- **Models/database:** entities, Alembic migrations, and safe legacy SQLite import tooling.
- **Authentication:** user/role lookup, access checks, sessions, and account services.
- **Routes/Blueprints:** current page, authentication, catalog, and admin endpoints; route-group extraction remains.
- **Storage/media:** local and optional S3-compatible storage. The S3 adapter is not provider-tested.
- **Templates/static:** presentation only; no secrets or provider credentials.
- **External rights/access:** rights verification is an admin attestation; territory data is not geolocated and non-free entitlements are not implemented.

The intended production data path is Flask-SQLAlchemy to an owner-selected MySQL service through an environment-provided URL. The explicit `import-legacy-sqlite` command imports a verified source backup into a separately migrated empty destination. It reads the source in read-only mode and refuses a non-empty target.

## External service boundaries

Cloud storage, metadata, email, advertising, and video delivery must be accessed through server-side adapters. Credentials belong in environment/provider secret settings, never templates or Git. An adapter is not considered operational until configured and verified against its provider. No hosting or external service is configured.

## Current limitations

- `backend/app/routes.py` still contains several route groups.
- Live MySQL and S3-compatible connectivity have not been verified; WSGI/Gunicorn has not been deployed.
- There is no API versioning; current routes are server-rendered HTML.
- Geolocation, entitlement/payment checks, rate limits, and full browser/device QA remain.
