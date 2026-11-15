import os
import sqlite3
import tempfile
import unittest

from sqlalchemy import create_engine, select

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import Movie, Setting, User, Watchlist, import_legacy_sqlite


class LegacySQLiteImportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.source_path = os.path.join(self.temp_dir.name, "legacy.db")
        self.target_path = os.path.join(self.temp_dir.name, "target.db")
        self.app = create_app(
            {
                "APP_ENV": "testing",
                "TESTING": True,
                "SECRET_KEY": "database-test-secret",
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.target_path}",
            }
        )
        self._create_legacy_source()
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.temp_dir.cleanup()

    def _create_legacy_source(self):
        source_engine = create_engine(f"sqlite:///{self.source_path}")
        db.metadata.create_all(
            source_engine,
            tables=[
                Movie.__table__,
                User.__table__,
                Watchlist.__table__,
                Setting.__table__,
            ],
        )
        with source_engine.begin() as connection:
            connection.execute(
                Movie.__table__.insert(),
                {
                    "id": 5,
                    "title": "Legacy Catalog Record",
                    "release_year": 2021,
                    "genre": "Drama",
                    "movie_url": "https://www.w3schools.com/html/mov_bbb.mp4",
                    "is_featured": False,
                },
            )
            connection.execute(
                User.__table__.insert(),
                {
                    "id": 8,
                    "username": "legacy_user",
                    "email": "legacy@example.test",
                    "password_hash": "existing-password-hash",
                    "is_admin": False,
                },
            )
            connection.execute(
                Watchlist.__table__.insert(),
                {"id": 3, "user_id": 8, "movie_id": 5},
            )
            connection.execute(
                Setting.__table__.insert(),
                {"key": "featured_movie_id", "value": "5"},
            )
        source_engine.dispose()

    def test_import_preserves_records_and_does_not_change_source(self):
        with self.app.app_context():
            counts = import_legacy_sqlite(self.source_path)
            self.assertEqual(
                counts,
                {"movies": 1, "users": 1, "watchlists": 1, "settings": 1},
            )
            movie = db.session.get(Movie, 5)
            self.assertEqual(movie.title, "Legacy Catalog Record")
            self.assertIsNone(movie.movie_url)
            self.assertEqual(db.session.get(User, 8).password_hash, "existing-password-hash")
            watchlist = db.session.scalar(select(Watchlist))
            self.assertEqual((watchlist.user_id, watchlist.movie_id), (8, 5))

        source = sqlite3.connect(f"file:{self.source_path}?mode=ro", uri=True)
        try:
            original_url = source.execute(
                "SELECT movie_url FROM movies WHERE id = 5"
            ).fetchone()[0]
        finally:
            source.close()
        self.assertEqual(original_url, "https://www.w3schools.com/html/mov_bbb.mp4")

    def test_import_refuses_nonempty_destination_without_partial_changes(self):
        with self.app.app_context():
            db.session.add(Setting(key="existing", value="preserve"))
            db.session.commit()
            with self.assertRaisesRegex(ValueError, "not empty"):
                import_legacy_sqlite(self.source_path)
            self.assertIsNone(db.session.get(Movie, 5))
            self.assertEqual(db.session.get(Setting, "existing").value, "preserve")

    def test_import_refuses_to_use_the_same_sqlite_file_as_source_and_target(self):
        same_file_app = create_app(
            {
                "APP_ENV": "testing",
                "TESTING": True,
                "SECRET_KEY": "same-file-test-secret",
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.source_path}",
            }
        )
        with same_file_app.app_context():
            with self.assertRaisesRegex(ValueError, "must be different"):
                import_legacy_sqlite(self.source_path)
            db.session.remove()
            db.engine.dispose()

    def test_import_rejects_an_unrecognized_source_schema(self):
        incompatible_path = os.path.join(self.temp_dir.name, "incompatible.db")
        connection = sqlite3.connect(incompatible_path)
        try:
            connection.executescript(
                """
                CREATE TABLE movies (id INTEGER PRIMARY KEY, title TEXT NOT NULL);
                CREATE TABLE users (id INTEGER PRIMARY KEY);
                CREATE TABLE watchlists (id INTEGER PRIMARY KEY);
                CREATE TABLE settings (key TEXT PRIMARY KEY);
                """
            )
        finally:
            connection.close()

        with self.app.app_context():
            with self.assertRaisesRegex(ValueError, "does not match the supported schema"):
                import_legacy_sqlite(incompatible_path)


if __name__ == "__main__":
    unittest.main()
