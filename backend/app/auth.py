from __future__ import annotations

from functools import wraps
from typing import Optional
from urllib.parse import urlsplit

from flask import flash, redirect, request, session, url_for

from .database import get_db


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def is_in_watchlist(user_id: int, movie_id: int) -> bool:
    row = get_db().execute(
        "SELECT 1 FROM watchlists WHERE user_id = ? AND movie_id = ?",
        (user_id, movie_id),
    ).fetchone()
    return row is not None


def user_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if get_current_user() is None:
            return redirect(url_for("main.login", next=request.full_path.rstrip("?")))
        return view_func(*args, **kwargs)

    return wrapper


def is_safe_redirect_target(target: Optional[str]) -> bool:
    if not target or target.startswith("//") or "\\" in target:
        return False
    parsed = urlsplit(target)
    return not parsed.scheme and not parsed.netloc and target.startswith("/")


def admin_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if user is None or user["is_admin"] != 1:
            flash("Administrator access is required.", "error")
            return redirect(url_for("main.home"))
        return view_func(*args, **kwargs)

    return wrapper
