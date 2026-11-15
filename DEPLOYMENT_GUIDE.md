# Deployment guide

## Runtime

The WSGI entry point is `wsgi:app`; the `Procfile` starts it with Gunicorn. The app expects the hosting platform to provide `PORT`. `/health` performs a database connectivity check and returns HTTP 503 when the database is unavailable.

## Required configuration

Before deploying, configure these values in the hosting provider's environment settings:

- `APP_ENV=production`
- `SECRET_KEY`: a long, randomly generated secret
- `DATABASE_URL`: a MySQL URL using the `mysql+pymysql://` driver

Never put production credentials in `.env.example`, source control, or build logs. Use the provider's secret manager. The repository does not choose or provision a hosting provider or database.

For private S3-compatible media, additionally configure `STORAGE_BACKEND=s3`, `S3_BUCKET`, and any required `S3_REGION` or `S3_ENDPOINT_URL`. Supply credentials only through the provider's credential store or workload identity. Do not select S3 until its bucket and credentials are available; the default is local storage, which may be ephemeral on hosted platforms.

## Database release

1. Back up the target database and verify that the backup can be read.
2. Review pending migration SQL and run `flask --app backend.app:create_app db upgrade` using the production environment.
3. Check `flask --app backend.app:create_app db current` and `/health` after the migration.
4. Create an administrator with `flask --app backend.app:create_app create-admin`; enter the password interactively.

Do not run schema creation against production. The application intentionally disables automatic schema creation in production.

## Before going live

- Configure HTTPS at the hosting provider and confirm proxy/TLS settings.
- Verify database and object-storage connectivity, backups, logs, and access controls.
- Confirm every published title has current, documented distribution rights for its territory.
- Verify real licensed media playback, seeking, download policy, and upload limits in a staging environment.
- Confirm expected service costs and provider terms directly with the owner before enabling any paid service.

No hosted deployment, MySQL instance, or object-storage provider has been activated or live-tested as part of this repository change.
