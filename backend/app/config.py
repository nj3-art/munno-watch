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
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("mysql://"):
    DATABASE_URL = DATABASE_URL.replace("mysql://", "mysql+pymysql://", 1)
if APP_ENV == "production" and not DATABASE_URL:
    raise RuntimeError("DATABASE_URL must be configured in production.")
if APP_ENV == "production" and not DATABASE_URL.startswith("mysql+pymysql://"):
    raise RuntimeError("DATABASE_URL must use the MySQL PyMySQL driver in production.")
if not DATABASE_URL:
    DATABASE_URL = f"sqlite:///{PROJECT_ROOT / 'cinezone.db'}"


class Config:
    APP_ENV = APP_ENV
    SECRET_KEY = SECRET_KEY
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PORT = int(os.environ.get("PORT", "5000"))
    DEBUG = APP_ENV == "development"
    TESTING = APP_ENV == "testing"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = APP_ENV == "production"
