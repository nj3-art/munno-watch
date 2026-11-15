import os
import re
from datetime import datetime, timezone

from flask import current_app, has_app_context
from sqlalchemy import select
from werkzeug.security import generate_password_hash

from .extensions import db
from .models import User


def ensure_db() -> None:
    if not has_app_context():
        raise RuntimeError("ensure_db must be called within an application context.")
    if current_app.config["APP_ENV"] == "production":
        raise RuntimeError(
            "Run Flask database migrations in production; automatic schema creation is disabled."
        )

    db.create_all()
    admin_password = os.environ.get("CINEZONE_ADMIN_PASSWORD")
    if admin_password and db.session.scalar(select(User.id).limit(1)) is None:
        username = os.environ.get("CINEZONE_ADMIN_USERNAME", "admin")
        email = os.environ.get("CINEZONE_ADMIN_EMAIL", "admin@cinezone.app")
        if len(admin_password) < 12 or len(admin_password) > 128:
            raise RuntimeError("CINEZONE_ADMIN_PASSWORD must be between 12 and 128 characters.")
        if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", username):
            raise RuntimeError("CINEZONE_ADMIN_USERNAME must be 3 to 32 letters, numbers or underscores.")
        if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise RuntimeError("CINEZONE_ADMIN_EMAIL must be a valid email address.")
        db.session.add(
            User(
                username=username,
                email=email,
                password_hash=generate_password_hash(admin_password),
                is_admin=True,
                created_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            )
        )
        db.session.commit()
