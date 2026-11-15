# CineZone

CineZone is a Flask movie-discovery application with rights-gated catalog and media routes. The repository does not include licensed movie files or production credentials.

## Run locally (Mac + VS Code)

1. Open the `Cinezone` folder in VS Code.
2. Open **Terminal → New Terminal** and confirm the terminal is at the repository root.
3. Create and activate a virtual environment, then install the project dependencies:

   ```sh
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. Start the development app with a database separate from the legacy `cinezone.db`:

   ```sh
   APP_ENV=development SECRET_KEY=local-development-only DATABASE_URL=sqlite:///cinezone-dev.db python3 cinezone.py
   ```

5. Open `http://127.0.0.1:5000`. The development database starts empty; add only metadata and media for which you have permission.
6. To create a local administrator, stop the server with **Control+C**, then run:

   ```sh
   APP_ENV=development SECRET_KEY=local-development-only DATABASE_URL=sqlite:///cinezone-dev.db flask --app backend.app:create_app create-admin
   ```

   Enter a unique username, email, and a password of at least 12 characters when prompted. Restart the app with the command in step 4.

The default SQLite URL is `cinezone-dev.db`, and local `.db` files are ignored by Git. Never point local initialization at the existing `cinezone.db` unless you have a separate, verified backup and have explicitly approved the migration procedure in [migrations/README](./migrations/README). Do not run development schema creation against production.

## Tests

With the virtual environment active, run:

```sh
python3 -m compileall -q backend cinezone.py wsgi.py tests migrations
python3 -m unittest discover -s tests -v
```

Tests use isolated temporary databases and synthetic file-signature fixtures; they do not prove external-provider connectivity or actual licensed playback.

## Project documentation

- [Project audit](./PROJECT_AUDIT.md) and [progress](./PROJECT_PROGRESS.md)
- [Development roadmap](./DEVELOPMENT_ROADMAP.md) and [architecture](./ARCHITECTURE.md)
- [Deployment guide](./DEPLOYMENT_GUIDE.md)

Hosting, MySQL, object storage, domain, advertising, and payment services are not configured. See the deployment guide for prerequisites and approval boundaries.
