import os
import secrets
from pathlib import Path


APP_ENV = os.environ.get("APP_ENV", "development").lower()
if APP_ENV not in {"development", "production", "testing"}:
    raise RuntimeError("APP_ENV must be development, testing or production.")

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if APP_ENV == "production":
        raise RuntimeError("SECRET_KEY must be configured in production.")
    SECRET_KEY = secrets.token_urlsafe(32)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Config:
    APP_ENV = APP_ENV
    SECRET_KEY = SECRET_KEY
    DATABASE_PATH = str(PROJECT_ROOT / "cinezone.db")
    PORT = int(os.environ.get("PORT", "5000"))
    DEBUG = APP_ENV == "development"
    TESTING = APP_ENV == "testing"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = APP_ENV == "production"
