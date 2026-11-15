import os
import re
import tempfile
import unittest
from unittest.mock import patch

from backend.app import create_app
from cinezone import app, ensure_db


class CineZoneAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.database_path = os.path.join(cls.temp_dir.name, "test.db")
        cls.original_config = {
            key: app.config[key]
            for key in ("DATABASE_PATH", "SECRET_KEY", "TESTING", "APP_ENV")
        }
        app.config.update(
            DATABASE_PATH=cls.database_path,
            SECRET_KEY="test-only-secret",
            TESTING=True,
            APP_ENV="testing",
        )
        with patch.dict(
            os.environ,
            {
                "CINEZONE_ADMIN_PASSWORD": "A-test-admin-password",
                "CINEZONE_ADMIN_USERNAME": "admin",
                "CINEZONE_ADMIN_EMAIL": "admin@example.test",
            },
        ):
            ensure_db(cls.database_path)

    @classmethod
    def tearDownClass(cls):
        app.config.update(cls.original_config)
        cls.temp_dir.cleanup()

    def setUp(self):
        self.client = app.test_client()

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

    def test_application_factory_registers_main_blueprint(self):
        test_app = create_app(
            {
                "APP_ENV": "testing",
                "DATABASE_PATH": self.database_path,
                "SECRET_KEY": "factory-test-secret",
                "TESTING": True,
            }
        )
        self.assertIn("main.home", test_app.view_functions)
        self.assertEqual(test_app.test_client().get("/").status_code, 200)

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
        self.login(username="new_user", password="long-enough-password")
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
