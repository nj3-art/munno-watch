from __future__ import annotations

from functools import wraps
from typing import Optional
from urllib.parse import urlsplit

from flask import flash, redirect, request, session, url_for
from sqlalchemy import select

from .extensions import db
from .models import User, Watchlist


def get_current_user() -> User | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


def is_in_watchlist(user_id: int, movie_id: int) -> bool:
    return db.session.scalar(
        select(Watchlist.id).where(
            Watchlist.user_id == user_id,
            Watchlist.movie_id == movie_id,
        )
    ) is not None


def user_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if user is None:
            return redirect(url_for("main.login", next=request.full_path.rstrip("?")))
        if hasattr(user, "is_active") and not user.is_active:
            session.pop("user_id", None)
            flash("Your account is not active.", "error")
            return redirect(url_for("main.login"))
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
        if user is None or not user.is_admin:
            flash("Administrator access is required.", "error")
            return redirect(url_for("main.home"))
        return view_func(*args, **kwargs)

    return wrapper
