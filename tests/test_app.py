import os
import re
import tempfile
import unittest
import base64
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import Movie, MovieRights, User
from backend.app.storage import StorageUnavailable, save_upload
from werkzeug.datastructures import FileStorage
from werkzeug.security import generate_password_hash


class CineZoneAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.database_path = os.path.join(cls.temp_dir.name, "test.db")
        cls.app = create_app(
            {
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{cls.database_path}",
                "MEDIA_STORAGE_PATH": os.path.join(cls.temp_dir.name, "media"),
                "SECRET_KEY": "test-only-secret",
                "TESTING": True,
                "APP_ENV": "testing",
            }
        )
        with cls.app.app_context():
            db.create_all()
            db.session.add_all(
                [
                    Movie(
                        id=1,
                        title="Regression Test Movie",
                        release_year=2024,
                        genre="Action",
                        description="Test-only record.",
                        availability="Free",
                        rating=8.0,
                        popularity=10.0,
                        rights=MovieRights(
                            rights_holder="Test Rights Holder",
                            license_reference="TEST-001",
                            territories="Worldwide",
                            license_start=date.today() - timedelta(days=30),
                            license_expiry=date.today() + timedelta(days=30),
                            rights_verified=True,
                            streaming_allowed=True,
                            download_allowed=True,
                            published=True,
                        ),
                    ),
                    User(
                        username="admin",
                        email="admin@example.test",
                        password_hash=generate_password_hash("A-test-admin-password"),
                        is_admin=True,
                    ),
                    User(
                        username="member",
                        email="member@example.test",
                        password_hash=generate_password_hash("A-test-member-password"),
                        is_admin=False,
                    ),
                ]
            )
            db.session.commit()

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.engine.dispose()
        cls.temp_dir.cleanup()

    def setUp(self):
        self.client = self.app.test_client()

    def csrf_token(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
        self.assertIsNotNone(match)
        return match.group(1).decode()

    def login(self, username="admin", password="A-test-admin-password", next_url=None):
        token = self.csrf_token("/login")
        form_data = {
            "csrf_token": token,
            "username": username,
            "password": password,
        }
        if next_url:
            form_data["next"] = next_url
        return self.client.post("/login", data=form_data, follow_redirects=False)

    def test_existing_pages_render(self):
        for path in ("/", "/movies", "/movie/1", "/watch/1", "/login", "/register", "/genre/Action"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_public_genre_and_watchlist_hide_unpublished_movies(self):
        with self.app.app_context():
            movie = Movie(
                title="Unpublished Action Title",
                genre="Action",
                availability="Free",
            )
            db.session.add(movie)
            db.session.commit()
            movie_id = movie.id

        genre_page = self.client.get("/genre/Action")
        self.assertEqual(genre_page.status_code, 200)
        self.assertNotIn(b"Unpublished Action Title", genre_page.data)

        self.login(username="member", password="A-test-member-password")
        token = self.csrf_token("/profile")
        response = self.client.post(
            f"/toggle-watchlist/{movie_id}",
            data={"csrf_token": token},
        )
        self.assertEqual(response.status_code, 404)
        profile = self.client.get("/profile")
        self.assertNotIn(b"Unpublished Action Title", profile.data)

    def test_watch_page_does_not_render_unverified_stream_urls(self):
        with self.app.app_context():
            movie = db.session.get(Movie, 1)
            movie.movie_url = "https://www.w3schools.com/html/mov_bbb.mp4"
            db.session.commit()

        response = self.client.get("/watch/1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"no verified local video file is configured", response.data)
        self.assertNotIn(b"w3schools.com", response.data)

    def test_application_factory_registers_main_blueprint(self):
        test_app = create_app(
            {
                "APP_ENV": "testing",
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.database_path}.factory",
                "MEDIA_STORAGE_PATH": os.path.join(self.temp_dir.name, "factory-media"),
                "SECRET_KEY": "factory-test-secret",
                "TESTING": True,
            }
        )
        with test_app.app_context():
            db.create_all()
        self.assertIn("main.home", test_app.view_functions)
        self.assertEqual(test_app.test_client().get("/").status_code, 200)
        with test_app.app_context():
            self.assertEqual(db.session.query(Movie).count(), 0)
            db.session.remove()
            db.engine.dispose()

    def test_blueprint_preserves_existing_public_route_paths(self):
        routes = {
            (rule.rule, rule.endpoint.removeprefix("main.")): rule.methods - {"HEAD", "OPTIONS"}
            for rule in self.app.url_map.iter_rules()
            if rule.endpoint.startswith("main.")
        }
        expected_routes = {
            ("/", "home"): {"GET"},
            ("/admin", "admin"): {"GET", "POST"},
            ("/genre/<string:genre_name>", "genre_page"): {"GET"},
            ("/login", "login"): {"GET", "POST"},
            ("/logout", "logout"): {"POST"},
            ("/movie/<int:movie_id>", "movie_detail"): {"GET"},
            ("/movies", "movies"): {"GET"},
            ("/profile", "profile"): {"GET"},
            ("/register", "register"): {"GET", "POST"},
            ("/toggle-watchlist/<int:movie_id>", "toggle_watchlist"): {"POST"},
            ("/watch/<int:movie_id>", "watch_movie"): {"GET"},
        }
        for route, methods in expected_routes.items():
            with self.subTest(route=route):
                self.assertEqual(routes.get(route), methods)

    def test_invalid_filter_values_return_bad_request(self):
        self.assertEqual(self.client.get("/movies?year=not-a-year").status_code, 400)
        self.assertEqual(self.client.get("/movies?rating=11").status_code, 400)

    def test_registration_rejects_short_password_and_accepts_valid_input(self):
        token = self.csrf_token("/register")
        response = self.client.post(
            "/register",
            data={
                "csrf_token": token,
                "username": "new_user",
                "email": "new@example.test",
                "password": "short",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Password must be between 12 and 128 characters.", response.data)

        token = self.csrf_token("/register")
        response = self.client.post(
            "/register",
            data={
                "csrf_token": token,
                "username": "new_user",
                "email": "new@example.test",
                "password": "long-enough-password",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/login")

    def test_login_rejects_external_redirect_target(self):
        response = self.login(next_url="https://attacker.example")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")

    def test_login_allows_local_redirect_target(self):
        response = self.login(next_url="/movies")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/movies")

    def test_logout_requires_post_and_csrf_token(self):
        self.assertEqual(self.client.get("/logout").status_code, 405)
        self.assertEqual(self.client.post("/logout").status_code, 400)

    def test_admin_route_remains_restricted(self):
        self.assertEqual(self.client.get("/admin").status_code, 302)
        self.login(username="member", password="A-test-member-password")
        self.assertEqual(self.client.get("/admin").status_code, 302)
        self.client.post("/logout", data={"csrf_token": self.csrf_token("/login")})
        self.login()
        self.assertEqual(self.client.get("/admin").status_code, 200)

    def test_movie_admin_routes_require_administrator_access(self):
        self.assertEqual(self.client.get("/admin/movies/new").status_code, 302)
        self.login(username="member", password="A-test-member-password")
        self.assertEqual(self.client.get("/admin/movies/new").status_code, 302)

    def test_admin_can_create_unpublished_movie_without_claiming_rights(self):
        self.login()
        token = self.csrf_token("/admin/movies/new")
        response = self.client.post(
            "/admin/movies/new",
            data={
                "csrf_token": token,
                "title": "Awaiting Rights Review",
                "description": "Not yet cleared for public viewing.",
                "availability": "Restricted",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            movie = db.session.scalar(
                db.select(Movie).where(Movie.title == "Awaiting Rights Review")
            )
            self.assertIsNotNone(movie)
            self.assertFalse(movie.rights.published)
            self.assertFalse(movie.rights.rights_verified)
            self.assertEqual(movie.availability, "Restricted")
            self.assertEqual(self.client.get(f"/movie/{movie.id}").status_code, 404)

    def test_admin_can_edit_and_unpublish_movie(self):
        self.login()
        token = self.csrf_token("/admin/movies/new")
        initial = self.client.post(
            "/admin/movies/new",
            data={
                "csrf_token": token,
                "title": "Editable Rights-Ready Movie",
                "description": "Catalog record before publication.",
                "genre": "Drama",
                "availability": "Free",
                "rights_holder": "Test Rights Holder",
                "license_reference": "TEST-EDIT-001",
                "territories": "Worldwide",
                "license_start": (date.today() - timedelta(days=1)).isoformat(),
                "license_expiry": (date.today() + timedelta(days=30)).isoformat(),
            },
        )
        self.assertEqual(initial.status_code, 302)
        with self.app.app_context():
            movie = db.session.scalar(
                db.select(Movie).where(Movie.title == "Editable Rights-Ready Movie")
            )
            movie_id = movie.id

        edit_token = self.csrf_token(f"/admin/movies/{movie_id}/edit")
        updated = self.client.post(
            f"/admin/movies/{movie_id}/edit",
            data={
                "csrf_token": edit_token,
                "title": "Edited Rights-Ready Movie",
                "description": "Updated catalog record.",
                "genre": "Drama",
                "availability": "Free",
                "rights_holder": "Test Rights Holder",
                "license_reference": "TEST-EDIT-001",
                "territories": "Worldwide",
                "license_start": (date.today() - timedelta(days=1)).isoformat(),
                "license_expiry": (date.today() + timedelta(days=30)).isoformat(),
                "rights_verified": "on",
                "streaming_allowed": "on",
                "published": "on",
            },
        )
        self.assertEqual(updated.status_code, 302)

        admin_token = self.csrf_token("/admin")
        unpublished = self.client.post(
            f"/admin/movies/{movie_id}/unpublish",
            data={"csrf_token": admin_token},
        )
        self.assertEqual(unpublished.status_code, 302)
        with self.app.app_context():
            movie = db.session.get(Movie, movie_id)
            self.assertEqual(movie.title, "Edited Rights-Ready Movie")
            self.assertTrue(movie.rights.rights_verified)
            self.assertFalse(movie.rights.published)
            self.assertEqual(self.client.get(f"/movie/{movie_id}").status_code, 404)

    def test_admin_cannot_publish_without_documented_verified_rights(self):
        self.login()
        token = self.csrf_token("/admin/movies/new")
        response = self.client.post(
            "/admin/movies/new",
            data={
                "csrf_token": token,
                "title": "Blocked Publication",
                "published": "on",
                "streaming_allowed": "on",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Verify documented rights", response.data)
        with self.app.app_context():
            self.assertIsNone(
                db.session.scalar(db.select(Movie).where(Movie.title == "Blocked Publication"))
            )

    def test_admin_upload_creates_rights_gated_range_stream_and_download(self):
        self.login()
        token = self.csrf_token("/admin/movies/new")
        minimal_mp4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 24
        one_pixel_png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5uoAAAAASUVORK5CYII="
        )
        response = self.client.post(
            "/admin/movies/new",
            data={
                "csrf_token": token,
                "title": "Licensed Test Asset",
                "availability": "Free",
                "rights_holder": "Test Rights Holder",
                "license_reference": "TEST-STREAM-001",
                "territories": "Worldwide",
                "license_start": (date.today() - timedelta(days=1)).isoformat(),
                "license_expiry": (date.today() + timedelta(days=30)).isoformat(),
                "rights_verified": "on",
                "streaming_allowed": "on",
                "download_allowed": "on",
                "published": "on",
                "video_file": (BytesIO(minimal_mp4), "../../licensed.mp4", "video/mp4"),
                "poster_file": (BytesIO(one_pixel_png), "cover.png", "image/png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            movie = db.session.scalar(
                db.select(Movie).where(Movie.title == "Licensed Test Asset")
            )
            movie_id = movie.id
            self.assertTrue(movie.rights.published)
            self.assertTrue(movie.assets.video_key.startswith("videos/"))
            self.assertTrue(movie.assets.poster_key.startswith("posters/"))

        visitor = self.app.test_client()
        poster_response = visitor.get(f"/poster/{movie_id}")
        self.assertEqual(poster_response.status_code, 200)
        self.assertEqual(poster_response.data, one_pixel_png)
        poster_response.close()
        streamed = visitor.get(f"/stream/{movie_id}", headers={"Range": "bytes=0-7"})
        self.assertEqual(streamed.status_code, 206)
        self.assertEqual(streamed.data, minimal_mp4[:8])
        self.assertTrue(streamed.headers["Content-Range"].startswith("bytes 0-7/"))
        streamed.close()
        downloaded = visitor.get(f"/download/{movie_id}")
        self.assertEqual(downloaded.status_code, 200)
        self.assertIn("attachment", downloaded.headers["Content-Disposition"])
        downloaded.close()

    def test_upload_rejects_mismatched_mime_and_unsafe_extension(self):
        self.login()
        token = self.csrf_token("/admin/movies/new")
        media_root = Path(self.temp_dir.name) / "media"
        existing_files = set(media_root.rglob("*")) if media_root.exists() else set()
        response = self.client.post(
            "/admin/movies/new",
            data={
                "csrf_token": token,
                "title": "Invalid Upload",
                "video_file": (BytesIO(b"not an executable"), "../../run.py", "text/x-python"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Unsupported video file extension", response.data)
        current_files = set(media_root.rglob("*")) if media_root.exists() else set()
        self.assertEqual(current_files, existing_files)

    def test_movie_is_hidden_until_licence_dates_are_active(self):
        self.login()
        token = self.csrf_token("/admin/movies/new")
        response = self.client.post(
            "/admin/movies/new",
            data={
                "csrf_token": token,
                "title": "Future Licence",
                "availability": "Free",
                "rights_holder": "Test Rights Holder",
                "license_reference": "TEST-FUTURE-001",
                "territories": "Worldwide",
                "license_start": (date.today() + timedelta(days=2)).isoformat(),
                "license_expiry": (date.today() + timedelta(days=30)).isoformat(),
                "rights_verified": "on",
                "streaming_allowed": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            movie = db.session.scalar(
                db.select(Movie).where(Movie.title == "Future Licence")
            )
            self.assertEqual(self.client.get(f"/movie/{movie.id}").status_code, 404)

    def test_expired_rights_block_stream_and_download(self):
        with self.app.app_context():
            movie = Movie(
                title="Expired Rights",
                availability="Free",
                rights=MovieRights(
                    rights_holder="Test Rights Holder",
                    license_reference="TEST-EXPIRED-001",
                    territories="Worldwide",
                    license_start=date.today() - timedelta(days=30),
                    license_expiry=date.today() - timedelta(days=1),
                    rights_verified=True,
                    streaming_allowed=True,
                    download_allowed=True,
                    published=True,
                ),
            )
            db.session.add(movie)
            db.session.commit()
            movie_id = movie.id

        visitor = self.app.test_client()
        self.assertEqual(visitor.get(f"/movie/{movie_id}").status_code, 404)
        self.assertEqual(visitor.get(f"/stream/{movie_id}").status_code, 404)
        self.assertEqual(visitor.get(f"/download/{movie_id}").status_code, 404)

    def test_health_endpoint_reports_database_status(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok"})

    def test_s3_configuration_is_optional_but_missing_bucket_is_explicit(self):
        s3_app = create_app(
            {
                "APP_ENV": "testing",
                "TESTING": True,
                "SECRET_KEY": "s3-test-secret",
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.database_path}.s3",
                "STORAGE_BACKEND": "s3",
                "S3_BUCKET": None,
            }
        )
        upload = FileStorage(
            stream=BytesIO(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 16),
            filename="movie.mp4",
            content_type="video/mp4",
        )
        with s3_app.app_context():
            with self.assertRaisesRegex(StorageUnavailable, "S3_BUCKET"):
                save_upload(upload, "video")

    def test_security_headers_are_present(self):
        response = self.client.get("/")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "SAMEORIGIN")
        self.assertEqual(response.headers["Referrer-Policy"], "strict-origin-when-cross-origin")


if __name__ == "__main__":
    unittest.main()
