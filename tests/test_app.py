import os
import re
import tempfile
import unittest

from backend.app import create_app
from backend.app.extensions import db
from backend.app.models import Movie, User
from werkzeug.security import generate_password_hash


class CineZoneAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.database_path = os.path.join(cls.temp_dir.name, "test.db")
        cls.app = create_app(
            {
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{cls.database_path}",
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
                        rating=8.0,
                        popularity=10.0,
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

    def test_watch_page_does_not_render_unverified_stream_urls(self):
        with self.app.app_context():
            movie = db.session.get(Movie, 1)
            movie.movie_url = "https://www.w3schools.com/html/mov_bbb.mp4"
            db.session.commit()

        response = self.client.get("/watch/1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"no verified source is configured", response.data)
        self.assertNotIn(b"w3schools.com", response.data)

    def test_application_factory_registers_main_blueprint(self):
        test_app = create_app(
            {
                "APP_ENV": "testing",
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{self.database_path}.factory",
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

    def test_security_headers_are_present(self):
        response = self.client.get("/")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "SAMEORIGIN")
        self.assertEqual(response.headers["Referrer-Policy"], "strict-origin-when-cross-origin")


if __name__ == "__main__":
    unittest.main()
