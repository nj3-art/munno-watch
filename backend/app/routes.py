from __future__ import annotations

import re
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from .auth import admin_required, get_current_user, is_in_watchlist, is_safe_redirect_target, user_required
from .extensions import db
from .metadata import MetadataConfigError, MetadataProviderError, get_movie as tmdb_get_movie, map_tmdb_movie, search_movies as tmdb_search_movies
from .models import (
    AuditLog,
    EmailVerificationToken,
    Favourite,
    Movie,
    MovieAsset,
    MovieDetails,
    MovieRights,
    MovieView,
    PasswordResetToken,
    Review,
    Setting,
    User,
    WatchHistory,
    Watchlist,
)
from .storage import (
    StorageUnavailable,
    UploadValidationError,
    delete_storage_key,
    save_upload,
    storage_has_key,
    storage_local_path,
    storage_url,
)


main = Blueprint("main", __name__)
MOVIE_PAGE_SIZE = 24

# Simple in-memory rate limiting (per-process). For production use a shared store.
_RATE_BUCKET = {}


def _rate_limited(key: str, limit: int, window_seconds: int) -> bool:
    if current_app.config.get("TESTING") or current_app.config.get("APP_ENV") == "testing":
        return False
    now = datetime.now(timezone.utc).timestamp()
    bucket = _RATE_BUCKET.setdefault(key, [])
    cutoff = now - window_seconds
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)
    if len(bucket) >= limit:
        return True
    bucket.append(now)
    return False


@main.before_app_request
def enforce_maintenance_mode():
    if request.endpoint in {"main.health", "static"}:
        return None
    try:
        row = db.session.get(Setting, "maintenance_mode")
        if row and row.value == "on":
            user = get_current_user()
            if not (user and user.is_admin):
                return render_template("maintenance.html"), 503
    except Exception:
        return None
    return None


def _published_movies_query():
    today = date.today()
    return select(Movie).join(MovieRights).where(
        MovieRights.published.is_(True),
        MovieRights.rights_verified.is_(True),
        MovieRights.rights_holder.is_not(None),
        MovieRights.license_reference.is_not(None),
        MovieRights.territories.is_not(None),
        MovieRights.license_start <= today,
        MovieRights.license_expiry >= today,
    )


def _rights_are_current(rights: Optional[MovieRights]) -> bool:
    today = date.today()
    return bool(
        rights
        and rights.published
        and rights.rights_verified
        and rights.rights_holder
        and rights.license_reference
        and rights.territories
        and rights.license_start
        and rights.license_start <= today
        and rights.license_expiry
        and rights.license_expiry >= today
    )


def _content_allowed(movie: Movie, action: str) -> bool:
    rights = movie.rights
    if not _rights_are_current(rights):
        return False
    if action == "stream" and not rights.streaming_allowed:
        return False
    if action == "download" and not rights.download_allowed:
        return False
    user = get_current_user()
    if rights.territories.strip().casefold() not in {"worldwide", "global", "all countries"}:
        return bool(user and user.is_admin)
    return (movie.availability or "").lower() == "free" or bool(user and user.is_admin)


def _public_movie(movie_id: int) -> Optional[Movie]:
    return db.session.scalar(_published_movies_query().where(Movie.id == movie_id))


def _record_admin_action(action: str, entity_type: str, entity_id: Optional[int]) -> None:
    actor = get_current_user()
    if not actor or not actor.is_admin:
        abort(403)
    db.session.add(
        AuditLog(
            actor_user_id=actor.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        )
    )


def get_genres() -> List[str]:
    return list(
        db.session.scalars(
            _published_movies_query()
            .with_only_columns(Movie.genre)
            .where(Movie.genre.is_not(None))
            .distinct()
            .order_by(Movie.genre)
        )
    )


def get_featured_movie() -> Optional[Movie]:
    setting = db.session.get(Setting, "featured_movie_id")
    if setting and setting.value:
        try:
            movie_id = int(setting.value)
        except ValueError:
            movie_id = None
        movie = _public_movie(movie_id) if movie_id is not None else None
        if movie:
            return movie
    return db.session.scalar(
        _published_movies_query()
        .order_by(Movie.release_year.desc(), Movie.created_at.desc())
        .limit(1)
    )


def get_movie(movie_id: int) -> Optional[Movie]:
    return db.session.get(Movie, movie_id)


def _requested_page() -> int:
    page_value = request.args.get("page", "1")
    try:
        page = int(page_value)
    except ValueError as error:
        raise ValueError("Page must be a whole number.") from error
    if page < 1 or page > 2_147_483_647:
        raise ValueError("Page must be a positive whole number.")
    return page


@main.route("/")
def home():
    featured = get_featured_movie()
    view_cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    trending_counts = (
        select(MovieView.movie_id, func.count(MovieView.id).label("view_count"))
        .where(MovieView.viewed_at >= view_cutoff)
        .group_by(MovieView.movie_id)
        .subquery()
    )
    popular_counts = (
        select(MovieView.movie_id, func.count(MovieView.id).label("view_count"))
        .group_by(MovieView.movie_id)
        .subquery()
    )
    trending = db.session.scalars(
        _published_movies_query()
        .join(trending_counts, trending_counts.c.movie_id == Movie.id)
        .order_by(trending_counts.c.view_count.desc())
        .limit(8)
    ).all()
    latest = db.session.scalars(
        _published_movies_query().order_by(Movie.release_year.desc()).limit(8)
    ).all()
    popular = db.session.scalars(
        _published_movies_query()
        .join(popular_counts, popular_counts.c.movie_id == Movie.id)
        .order_by(popular_counts.c.view_count.desc())
        .limit(8)
    ).all()
    recommended_query = _published_movies_query().order_by(Movie.release_year.desc()).limit(6)
    if featured and featured.genre:
        recommended_query = recommended_query.where(Movie.genre == featured.genre)
    else:
        recommended_query = recommended_query.where(Movie.id == -1)
    recommended = db.session.scalars(recommended_query).all()
    recently_added = db.session.scalars(
        _published_movies_query().order_by(Movie.created_at.desc()).limit(8)
    ).all()
    genres = get_genres()
    return render_template(
        "index.html",
        featured=featured,
        sections=[
            {"title": "Trending (30 days)", "movies": trending},
            {"title": "Latest Releases", "movies": latest},
            {"title": "Most Viewed", "movies": popular},
            {"title": "Recommended For You", "movies": recommended},
            {"title": "Recently Added", "movies": recently_added},
        ],
        genres=genres,
        collections=genres[:8],
    )


@main.route("/movies")
def movies():
    query = _published_movies_query()
    search_term = request.args.get("q", "").strip()
    genre = request.args.get("genre", "").strip()
    release_year = request.args.get("year", "").strip()
    language = request.args.get("language", "").strip()
    rating = request.args.get("rating", "").strip()
    availability = request.args.get("availability", "").strip()
    sort = request.args.get("sort", "newest")

    if search_term:
        like_term = f"%{search_term}%"
        query = query.where(
            or_(
                Movie.title.ilike(like_term),
                Movie.genre.ilike(like_term),
                Movie.description.ilike(like_term),
                Movie.keywords.ilike(like_term),
                Movie.director.ilike(like_term),
            )
        )

    if genre:
        query = query.where(Movie.genre == genre)

    if release_year:
        try:
            year = int(release_year)
        except ValueError:
            abort(400, description="Release year must be a whole number.")
        if year < 1888 or year > datetime.now(timezone.utc).year + 5:
            abort(400, description="Release year is outside the supported range.")
        query = query.where(Movie.release_year == year)

    if language:
        query = query.where(Movie.language == language)

    if rating:
        try:
            minimum_rating = float(rating)
        except ValueError:
            abort(400, description="Rating must be a number.")
        if not 0 <= minimum_rating <= 10:
            abort(400, description="Rating must be between 0 and 10.")
        query = query.where(Movie.rating >= minimum_rating)

    if availability:
        query = query.where(Movie.availability == availability)

    sort_options = {
        "newest": (Movie.release_year.desc(), Movie.created_at.desc()),
        "oldest": (Movie.release_year.asc(), Movie.created_at.desc()),
        "rated": (Movie.rating.desc(), Movie.release_year.desc()),
        "alpha": (Movie.title.asc(),),
    }
    if sort not in sort_options and sort != "popular":
        abort(400, description="Choose a valid sort order.")
    if sort == "popular":
        view_counts = (
            select(MovieView.movie_id, func.count(MovieView.id).label("view_count"))
            .group_by(MovieView.movie_id)
            .subquery()
        )
        query = query.outerjoin(view_counts, view_counts.c.movie_id == Movie.id).order_by(
            func.coalesce(view_counts.c.view_count, 0).desc(), Movie.title.asc()
        )
    else:
        query = query.order_by(*sort_options.get(sort, sort_options["newest"]))

    try:
        page = _requested_page()
    except ValueError as error:
        abort(400, description=str(error))
    pagination = db.paginate(query, page=page, per_page=MOVIE_PAGE_SIZE)
    return render_template(
        "movies.html",
        movies=pagination.items,
        pagination=pagination,
        pagination_args={
            key: value for key, value in request.args.items() if key != "page"
        },
        genres=get_genres(),
        current_query=search_term,
        current_sort=sort,
    )


@main.route("/movie/<int:movie_id>")
def movie_detail(movie_id: int):
    movie = _public_movie(movie_id)
    if movie is None:
        abort(404)

    related = db.session.scalars(
        _published_movies_query()
        .where(Movie.genre == movie.genre, Movie.id != movie_id)
        .order_by(Movie.release_year.desc())
        .limit(4)
    ).all()
    user = get_current_user()
    in_watchlist = bool(user and is_in_watchlist(user.id, movie_id))
    in_favourite = bool(
        user and db.session.scalar(select(Favourite.id).where(Favourite.user_id == user.id, Favourite.movie_id == movie_id))
    )
    db.session.add(
        MovieView(
            movie_id=movie.id,
            viewed_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        )
    )
    # Record/refresh watch history entry for continue-watching features when logged in
    if user:
        entry = db.session.scalar(select(WatchHistory).where(WatchHistory.user_id == user.id, WatchHistory.movie_id == movie_id))
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        if not entry:
            db.session.add(WatchHistory(user_id=user.id, movie_id=movie_id, progress_seconds=0, completed=False, last_watched_at=now))
        else:
            entry.last_watched_at = now
    db.session.commit()
    has_video = bool(movie.assets and storage_has_key(movie.assets.video_key))
    can_stream = _content_allowed(movie, "stream")
    can_download = _content_allowed(movie, "download")
    reviews = db.session.scalars(select(Review).where(Review.movie_id == movie.id).order_by(Review.created_at.desc()).limit(20)).all()
    user_review = db.session.scalar(select(Review).where(Review.movie_id == movie.id, Review.user_id == user.id)) if user else None
    return render_template(
        "movie.html",
        movie=movie,
        related=related,
        in_watchlist=in_watchlist,
        in_favourite=in_favourite,
        has_video=has_video,
        can_stream=can_stream,
        can_download=can_download,
        reviews=reviews,
        user_review=user_review,
    )


@main.route("/movie/<int:movie_id>/review", methods=["POST"])
@user_required
def submit_review(movie_id: int):
    if _public_movie(movie_id) is None:
        abort(404)
    rating_raw = request.form.get("rating", "").strip()
    body = request.form.get("body", "").strip()[:2000]
    rating = None
    if rating_raw:
        try:
            rating = int(rating_raw)
        except ValueError:
            rating = None
        if rating is not None and rating not in range(1, 11):
            flash("Rating must be between 1 and 10.", "error")
            return redirect(url_for("main.movie_detail", movie_id=movie_id))
    user = get_current_user()
    review = db.session.scalar(select(Review).where(Review.user_id == user.id, Review.movie_id == movie_id))
    if not review:
        review = Review(user_id=user.id, movie_id=movie_id, created_at=_now_str())
        db.session.add(review)
    review.rating = rating
    review.body = body or None
    review.created_at = _now_str()
    db.session.commit()
    flash("Review saved.", "success")
    return redirect(url_for("main.movie_detail", movie_id=movie_id))


@main.route("/watch/<int:movie_id>")
def watch_movie(movie_id: int):
    movie = _public_movie(movie_id)
    if movie is None:
        abort(404)
    if not _content_allowed(movie, "stream"):
        abort(403)
    has_video = bool(movie.assets and storage_has_key(movie.assets.video_key))
    return render_template("watch.html", movie=movie, has_video=has_video)


@main.route("/stream/<int:movie_id>")
def stream_movie(movie_id: int):
    movie = _public_movie(movie_id)
    if movie is None:
        abort(404)
    if not _content_allowed(movie, "stream"):
        abort(403)
    asset = movie.assets
    if asset and asset.video_key:
        try:
            signed_url = storage_url(asset.video_key)
        except StorageUnavailable as error:
            abort(503, description=str(error))
        if signed_url:
            return redirect(signed_url)
    path = storage_local_path(asset.video_key if asset else None)
    if path is None:
        abort(404, description="No local video file is available.")
    return send_file(path, mimetype=asset.video_mime, conditional=True, max_age=0)


@main.route("/trailer/<int:movie_id>")
def trailer_movie(movie_id: int):
    movie = _public_movie(movie_id)
    if movie is None:
        abort(404)
    if not _content_allowed(movie, "stream"):
        abort(403)
    asset = movie.assets
    if asset and asset.trailer_key:
        try:
            signed_url = storage_url(asset.trailer_key)
        except StorageUnavailable as error:
            abort(503, description=str(error))
        if signed_url:
            return redirect(signed_url)
    path = storage_local_path(asset.trailer_key if asset else None)
    if path is None:
        abort(404, description="No local trailer file is available.")
    return send_file(path, mimetype=asset.trailer_mime, conditional=True, max_age=0)


@main.route("/download/<int:movie_id>")
def download_movie(movie_id: int):
    movie = _public_movie(movie_id)
    if movie is None:
        abort(404)
    if not _content_allowed(movie, "download"):
        abort(403)
    asset = movie.assets
    title = secure_filename(movie.title) or "movie"
    extension = Path(asset.video_key).suffix.lower() if asset and asset.video_key else ".mp4"
    download_name = f"{title}{extension}"
    if asset and asset.video_key:
        try:
            signed_url = storage_url(
                asset.video_key, as_attachment=True, download_name=download_name
            )
        except StorageUnavailable as error:
            abort(503, description=str(error))
        if signed_url:
            return redirect(signed_url)
    path = storage_local_path(asset.video_key if asset else None)
    if path is None:
        abort(404, description="No local video file is available.")
    return send_file(
        path,
        mimetype=asset.video_mime,
        as_attachment=True,
        download_name=f"{title}{extension}",
        conditional=True,
        max_age=0,
    )


@main.route("/poster/<int:movie_id>")
def poster(movie_id: int):
    movie = _public_movie(movie_id)
    if movie is None:
        abort(404)
    asset = movie.assets
    if asset and asset.poster_key:
        try:
            signed_url = storage_url(asset.poster_key)
        except StorageUnavailable as error:
            abort(503, description=str(error))
        if signed_url:
            return redirect(signed_url)
    path = storage_local_path(asset.poster_key if asset else None)
    if path is None:
        abort(404)
    return send_file(path, mimetype=asset.poster_mime, conditional=True, max_age=3600)


@main.route("/toggle-watchlist/<int:movie_id>", methods=["POST"])
@user_required
def toggle_watchlist(movie_id: int):
    user = get_current_user()
    if _public_movie(movie_id) is None:
        abort(404)
    if is_in_watchlist(user.id, movie_id):
        entry = db.session.scalar(
            select(Watchlist).where(
                Watchlist.user_id == user.id,
                Watchlist.movie_id == movie_id,
            )
        )
        db.session.delete(entry)
        flash("Removed from your watchlist.", "success")
    else:
        db.session.add(
            Watchlist(
                user_id=user.id,
                movie_id=movie_id,
                created_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            )
        )
        flash("Added to your watchlist.", "success")
    db.session.commit()
    return redirect(request.referrer or url_for("main.movie_detail", movie_id=movie_id))


@main.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not username or not email or not password:
            flash("Please complete all required fields.", "error")
            return render_template("register.html")

        if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", username):
            flash("Username must be 3 to 32 characters using letters, numbers or underscores.", "error")
            return render_template("register.html")

        if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("Please enter a valid email address.", "error")
            return render_template("register.html")

        if len(password) < 12 or len(password) > 128:
            flash("Password must be between 12 and 128 characters.", "error")
            return render_template("register.html")

        if db.session.scalar(
            select(User.id).where(or_(User.username == username, User.email == email))
        ):
            flash("A user with that username or email already exists.", "error")
            return render_template("register.html")

        db.session.add(
            User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                is_admin=False,
                created_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            )
        )
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("A user with that username or email already exists.", "error")
            return render_template("register.html")
        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("main.login"))

    return render_template("register.html")


@main.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
        if _rate_limited(f"login:{ip}", 10, 300):
            flash("Too many login attempts. Please try again later.", "error")
            return render_template("login.html"), 429
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db.session.scalar(
            select(User).where(or_(User.username == username, User.email == username))
        )

        if not user or not check_password_hash(user.password_hash, password):
            flash("Invalid username or password.", "error")
            return render_template("login.html")
        if hasattr(user, "is_active") and not user.is_active:
            flash("Your account is not active. Contact support if this is unexpected.", "error")
            return render_template("login.html")

        session.clear()
        session["user_id"] = user.id
        flash("Welcome back to CineZone.", "success")
        next_url = request.form.get("next") or request.args.get("next")
        if not is_safe_redirect_target(next_url):
            next_url = url_for("main.home")
        return redirect(next_url)

    return render_template("login.html")


@main.route("/logout", methods=["POST"])
def logout():
    session.pop("user_id", None)
    flash("You have been logged out.", "success")
    return redirect(url_for("main.home"))


@main.route("/profile")
@user_required
def profile():
    user = get_current_user()
    watchlist = db.session.scalars(
        _published_movies_query()
        .join(Watchlist, Watchlist.movie_id == Movie.id)
        .where(Watchlist.user_id == user.id)
        .order_by(Watchlist.created_at.desc())
    ).all()
    return render_template("profile.html", user=user, watchlist=watchlist)


def _admin_movie_values(movie: Optional[Movie]) -> dict[str, object]:
    details = movie.details if movie else None
    rights = movie.rights if movie else None
    return {
        "title": movie.title if movie else "",
        "description": movie.description if movie else "",
        "release_year": movie.release_year if movie and movie.release_year else "",
        "runtime_minutes": details.runtime_minutes if details and details.runtime_minutes else "",
        "genre": movie.genre if movie else "",
        "cast_members": details.cast_members if details else "",
        "director": movie.director if movie else "",
        "language": movie.language if movie else "",
        "rating": movie.rating if movie and movie.rating is not None else "",
        "availability": (
            movie.availability
            if movie and movie.availability in {"Free", "Members", "Restricted"}
            else "Restricted" if movie else "Free"
        ),
        "rights_holder": rights.rights_holder if rights else "",
        "license_reference": rights.license_reference if rights else "",
        "territories": rights.territories if rights else "",
        "license_start": rights.license_start.isoformat() if rights and rights.license_start else "",
        "license_expiry": rights.license_expiry.isoformat() if rights and rights.license_expiry else "",
        "rights_verified": rights.rights_verified if rights else False,
        "streaming_allowed": rights.streaming_allowed if rights else False,
        "download_allowed": rights.download_allowed if rights else False,
        "published": rights.published if rights else False,
    }


def _render_admin_movie_form(
    movie: Optional[Movie], values: Optional[dict[str, object]] = None, status: int = 200
):
    base_values = _admin_movie_values(movie)
    if values:
        base_values.update(values)
    return (
        render_template(
            "admin_movie_form.html",
            movie=movie,
            values=base_values,
            assets=movie.assets if movie else None,
            current_year=date.today().year + 5,
        ),
        status,
    )


def _date_field(value: str, label: str) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} must be a valid date.") from error


def _validated_movie_fields(form) -> tuple[dict[str, object], dict[str, object]]:
    title = form.get("title", "").strip()
    if not title or len(title) > 255:
        raise ValueError("Title is required and must be 255 characters or fewer.")

    def optional_int(name: str, label: str, minimum: int, maximum: int) -> Optional[int]:
        value = form.get(name, "").strip()
        if not value:
            return None
        try:
            number = int(value)
        except ValueError as error:
            raise ValueError(f"{label} must be a whole number.") from error
        if not minimum <= number <= maximum:
            raise ValueError(f"{label} must be between {minimum} and {maximum}.")
        return number

    release_year = optional_int("release_year", "Release year", 1888, date.today().year + 5)
    runtime = optional_int("runtime_minutes", "Runtime", 1, 1000)
    rating_value = form.get("rating", "").strip()
    try:
        rating = float(rating_value) if rating_value else None
    except ValueError as error:
        raise ValueError("Rating must be a number.") from error
    if rating is not None and not 0 <= rating <= 10:
        raise ValueError("Rating must be between 0 and 10.")

    availability = form.get("availability", "Free").strip()
    if availability not in {"Free", "Members", "Restricted"}:
        raise ValueError("Choose a valid content access level.")
    movie_fields: dict[str, object] = {
        "title": title,
        "description": form.get("description", "").strip()[:10000],
        "release_year": release_year,
        "genre": form.get("genre", "").strip()[:100] or None,
        "director": form.get("director", "").strip()[:255] or None,
        "language": form.get("language", "").strip()[:100] or None,
        "rating": rating,
        "availability": availability,
        "keywords": form.get("keywords", "").strip()[:2000] or None,
    }

    rights_verified = form.get("rights_verified") == "on"
    streaming_allowed = form.get("streaming_allowed") == "on"
    download_allowed = form.get("download_allowed") == "on"
    published = form.get("published") == "on"
    rights_values: dict[str, object] = {
        "rights_holder": form.get("rights_holder", "").strip()[:255] or None,
        "license_reference": form.get("license_reference", "").strip()[:255] or None,
        "territories": form.get("territories", "").strip()[:2000] or None,
        "license_start": _date_field(form.get("license_start", "").strip(), "Licence start"),
        "license_expiry": _date_field(form.get("license_expiry", "").strip(), "Licence expiry"),
        "rights_verified": rights_verified,
        "streaming_allowed": streaming_allowed,
        "download_allowed": download_allowed,
        "published": published,
    }
    if (streaming_allowed or download_allowed or published) and not rights_verified:
        raise ValueError("Verify documented rights before enabling access or publishing.")
    if rights_verified or streaming_allowed or download_allowed or published:
        required = (
            rights_values["rights_holder"],
            rights_values["license_reference"],
            rights_values["territories"],
            rights_values["license_start"],
            rights_values["license_expiry"],
        )
        if not all(required):
            raise ValueError(
                "Rights holder, licence reference, territories, and licence dates are required."
            )
        if rights_values["license_start"] > rights_values["license_expiry"]:
            raise ValueError("Licence expiry must not be before its start date.")
        if published and (
            rights_values["license_start"] > date.today()
            or rights_values["license_expiry"] < date.today()
        ):
            raise ValueError("Only a licence active today can be published.")
    details_values = {
        "runtime_minutes": runtime,
        "cast_members": form.get("cast_members", "").strip()[:5000] or None,
    }
    return movie_fields, {"rights": rights_values, "details": details_values}


def _save_admin_movie(movie: Optional[Movie]):
    try:
        movie_fields, related_values = _validated_movie_fields(request.form)
    except ValueError as error:
        flash(str(error), "error")
        return _render_admin_movie_form(movie, request.form, 400)

    created = movie is None
    if movie is None:
        movie = Movie(
            created_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        )
        db.session.add(movie)
    for field, value in movie_fields.items():
        setattr(movie, field, value)
    if not movie.created_at:
        movie.created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    rights = movie.rights or MovieRights(movie=movie)
    details = movie.details or MovieDetails(movie=movie)
    db.session.add_all((rights, details))
    for field, value in related_values["rights"].items():
        setattr(rights, field, value)
    for field, value in related_values["details"].items():
        setattr(details, field, value)

    asset = movie.assets
    saved_uploads = []
    replaced_keys = []
    upload_fields = (
        ("poster_file", "poster", "poster_key", "poster_mime"),
        ("trailer_file", "trailer", "trailer_key", "trailer_mime"),
        ("video_file", "video", "video_key", "video_mime"),
    )
    try:
        for field_name, kind, key_field, mime_field in upload_fields:
            upload = request.files.get(field_name)
            if not upload or not upload.filename:
                continue
            stored = save_upload(upload, kind)
            saved_uploads.append(stored.key)
            if asset is None:
                asset = MovieAsset(movie=movie)
                db.session.add(asset)
            old_key = getattr(asset, key_field)
            if old_key:
                replaced_keys.append(old_key)
            setattr(asset, key_field, stored.key)
            setattr(asset, mime_field, stored.mime_type)
            if kind == "video":
                asset.video_size = stored.size
        db.session.flush()
        _record_admin_action(
            "movie.created" if created else "movie.updated",
            "movie",
            movie.id,
        )
        db.session.commit()
    except (UploadValidationError, StorageUnavailable) as error:
        db.session.rollback()
        for key in saved_uploads:
            delete_storage_key(key)
        flash(str(error), "error")
        return _render_admin_movie_form(None if created else movie, request.form, 400)
    except IntegrityError:
        db.session.rollback()
        for key in saved_uploads:
            delete_storage_key(key)
        flash("The movie could not be saved because its data conflicts with an existing record.", "error")
        return _render_admin_movie_form(None if created else movie, request.form, 400)

    for key in replaced_keys:
        delete_storage_key(key)
    flash("Movie created successfully." if created else "Movie updated successfully.", "success")
    return redirect(url_for("main.edit_admin_movie", movie_id=movie.id))


@main.route("/admin", methods=["GET", "POST"])
@admin_required
def admin():
    if request.method == "POST":
        movie_id = request.form.get("featured_movie_id")
        if movie_id:
            try:
                selected_movie_id = int(movie_id)
            except ValueError:
                abort(400, description="Featured movie ID must be a whole number.")
            if _public_movie(selected_movie_id) is None:
                abort(400, description="Selected featured movie does not exist.")
            setting = db.session.get(Setting, "featured_movie_id")
            if setting is None:
                setting = Setting(key="featured_movie_id", value=str(selected_movie_id))
                db.session.add(setting)
            else:
                setting.value = str(selected_movie_id)
            _record_admin_action("movie.featured", "movie", selected_movie_id)
            db.session.commit()
            flash("Featured movie updated successfully.", "success")

    search = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "all")
    if status_filter not in {"all", "published", "unpublished"}:
        abort(400, description="Choose a valid publication filter.")
    movie_query = select(Movie).order_by(Movie.title.asc())
    if status_filter == "published":
        movie_query = movie_query.join(MovieRights).where(MovieRights.published.is_(True))
    elif status_filter == "unpublished":
        movie_query = movie_query.outerjoin(MovieRights).where(
            or_(MovieRights.movie_id.is_(None), MovieRights.published.is_(False))
        )
    if search:
        movie_query = movie_query.where(
            or_(Movie.title.ilike(f"%{search}%"), Movie.genre.ilike(f"%{search}%"))
        )
    movies = db.session.scalars(movie_query).all()
    current_featured = get_featured_movie()
    featured_options = db.session.scalars(
        _published_movies_query().order_by(Movie.title.asc())
    ).all()
    users = db.session.scalars(select(User).order_by(User.created_at.desc()).limit(25)).all()
    audit_logs = db.session.scalars(
        select(AuditLog).order_by(AuditLog.id.desc()).limit(25)
    ).all()
    return render_template(
        "admin.html",
        movies=movies,
        current_featured=current_featured,
        featured_options=featured_options,
        search=search,
        status_filter=status_filter,
        users=users,
        audit_logs=audit_logs,
        upload_status={
            movie.id: bool(movie.assets and movie.assets.video_key) for movie in movies
        },
    )


@main.route("/admin/movies/new", methods=["GET", "POST"])
@admin_required
def new_admin_movie():
    if request.method == "POST":
        return _save_admin_movie(None)
    return _render_admin_movie_form(None)


@main.route("/admin/movies/<int:movie_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_admin_movie(movie_id: int):
    movie = get_movie(movie_id)
    if movie is None:
        abort(404)
    if request.method == "POST":
        return _save_admin_movie(movie)
    return _render_admin_movie_form(movie)


@main.route("/admin/movies/<int:movie_id>/unpublish", methods=["POST"])
@admin_required
def unpublish_admin_movie(movie_id: int):
    movie = get_movie(movie_id)
    if movie is None:
        abort(404)
    if movie.rights:
        movie.rights.published = False
    _record_admin_action("movie.unpublished", "movie", movie.id)
    db.session.commit()
    flash("Movie is unpublished.", "success")
    return redirect(url_for("main.admin"))


@main.route("/trending")
def trending():
    return redirect(url_for("main.movies", sort="popular"))


@main.route("/latest")
def latest():
    return redirect(url_for("main.movies", sort="newest"))


@main.route("/search")
def search():
    """Dedicated search page (reuses movie discovery)."""
    # Delegate to movies view logic by rendering same behavior
    args = request.args.to_dict(flat=True)
    if not args.get("sort"):
        args["sort"] = "newest"
    # Reuse /movies handler output expectations by calling its query path inline
    with current_app.test_request_context("/movies?" + "&".join(f"{k}={v}" for k, v in request.args.items())):
        pass
    # Simpler: replicate lightweight search rendering
    search_term = request.args.get("q", "").strip()
    genre = request.args.get("genre", "").strip()
    sort = request.args.get("sort", "newest")
    try:
        page = _requested_page()
    except ValueError as error:
        abort(400, description=str(error))
    query = _published_movies_query()
    if search_term:
        like_term = f"%{search_term}%"
        query = query.where(or_(Movie.title.ilike(like_term), Movie.genre.ilike(like_term), Movie.description.ilike(like_term), Movie.keywords.ilike(like_term), Movie.director.ilike(like_term)))
    if genre:
        query = query.where(Movie.genre == genre)
    sort_options = {"newest": (Movie.release_year.desc(), Movie.created_at.desc()), "oldest": (Movie.release_year.asc(), Movie.created_at.desc()), "rated": (Movie.rating.desc(), Movie.release_year.desc()), "alpha": (Movie.title.asc(),)}
    if sort == "popular":
        view_counts = select(MovieView.movie_id, func.count(MovieView.id).label("view_count")).group_by(MovieView.movie_id).subquery()
        query = query.outerjoin(view_counts, view_counts.c.movie_id == Movie.id).order_by(func.coalesce(view_counts.c.view_count, 0).desc(), Movie.title.asc())
    else:
        query = query.order_by(*sort_options.get(sort, sort_options["newest"]))
    pagination = db.paginate(query, page=page, per_page=MOVIE_PAGE_SIZE)
    return render_template("search.html", movies=pagination.items if (search_term or genre) else [], pagination=pagination, pagination_args={k: v for k, v in request.args.items() if k != "page"}, genres=get_genres(), current_query=search_term, current_sort=sort)


@main.route("/genres")
def genres():
    return render_template("genres.html", genres=get_genres())


@main.route("/continue-watching")
def continue_watching():
    user = get_current_user()
    items = []
    if user:
        items = db.session.scalars(
            _published_movies_query()
            .join(WatchHistory, WatchHistory.movie_id == Movie.id)
            .where(WatchHistory.user_id == user.id, WatchHistory.completed.is_(False))
            .order_by(WatchHistory.last_watched_at.desc())
            .limit(24)
        ).all()
        if not items:
            items = db.session.scalars(
                _published_movies_query()
                .join(Watchlist, Watchlist.movie_id == Movie.id)
                .where(Watchlist.user_id == user.id)
                .order_by(Watchlist.created_at.desc())
                .limit(24)
            ).all()
    return render_template("continue_watching.html", items=items)


@main.route("/about")
def about():
    return render_template("about.html")


@main.route("/contact")
def contact():
    contact_email = db.session.scalar(select(Setting.value).where(Setting.key == "contact_email"))
    return render_template("contact.html", contact_email=contact_email)


@main.route("/privacy")
def privacy_policy():
    return render_template("privacy.html")


@main.route("/terms")
def terms():
    return render_template("terms.html")


@main.route("/copyright")
def copyright_policy():
    return render_template("copyright.html")


@main.route("/robots.txt")
def robots_txt():
    content = "User-agent: *\nAllow: /\nSitemap: " + url_for("main.sitemap_xml", _external=True) + "\n"
    return current_app.response_class(content, mimetype="text/plain")


@main.route("/sitemap.xml")
def sitemap_xml():
    pages = [
        url_for("main.home", _external=True),
        url_for("main.movies", _external=True),
        url_for("main.genres", _external=True),
        url_for("main.trending", _external=True),
        url_for("main.latest", _external=True),
        url_for("main.search", _external=True),
        url_for("main.about", _external=True),
        url_for("main.contact", _external=True),
        url_for("main.privacy_policy", _external=True),
        url_for("main.terms", _external=True),
        url_for("main.copyright_policy", _external=True),
    ]
    movie_ids = db.session.scalars(_published_movies_query().with_only_columns(Movie.id)).all()
    for mid in movie_ids:
        pages.append(url_for("main.movie_detail", movie_id=mid, _external=True))
    for g in get_genres():
        pages.append(url_for("main.genre_page", genre_name=g, _external=True))
    urls = "".join(f"<url><loc>{p}</loc></url>" for p in pages)
    xml = '<?xml version="1.0" encoding="UTF-8"?>' + f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return current_app.response_class(xml, mimetype="application/xml")


def _now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _new_token():
    return secrets.token_urlsafe(32)


@main.route("/watchlist")
@user_required
def watchlist_page():
    user = get_current_user()
    movies = db.session.scalars(
        _published_movies_query()
        .join(Watchlist, Watchlist.movie_id == Movie.id)
        .where(Watchlist.user_id == user.id)
        .order_by(Watchlist.created_at.desc())
    ).all()
    return render_template("watchlist.html", movies=movies)


@main.route("/favourites")
@user_required
def favourites_page():
    user = get_current_user()
    movies = db.session.scalars(
        _published_movies_query()
        .join(Favourite, Favourite.movie_id == Movie.id)
        .where(Favourite.user_id == user.id)
        .order_by(Favourite.created_at.desc())
    ).all()
    return render_template("favourites.html", movies=movies)


@main.route("/toggle-favourite/<int:movie_id>", methods=["POST"])
@user_required
def toggle_favourite(movie_id: int):
    user = get_current_user()
    if _public_movie(movie_id) is None:
        abort(404)
    entry = db.session.scalar(select(Favourite).where(Favourite.user_id == user.id, Favourite.movie_id == movie_id))
    if entry:
        db.session.delete(entry)
        flash("Removed from favourites.", "success")
    else:
        db.session.add(Favourite(user_id=user.id, movie_id=movie_id, created_at=_now_str()))
        flash("Added to favourites.", "success")
    db.session.commit()
    return redirect(request.referrer or url_for("main.movie_detail", movie_id=movie_id))


@main.route("/history")
@user_required
def watch_history_page():
    user = get_current_user()
    entries = db.session.scalars(
        select(WatchHistory).where(WatchHistory.user_id == user.id).order_by(WatchHistory.last_watched_at.desc()).limit(100)
    ).all()
    movie_ids = [e.movie_id for e in entries]
    movies = {m.id: m for m in db.session.scalars(select(Movie).where(Movie.id.in_(movie_ids))).all()} if movie_ids else {}
    return render_template("continue_watching.html", items=[movies[e.movie_id] for e in entries if e.movie_id in movies], history_mode=True)


@main.route("/api/watch-progress/<int:movie_id>", methods=["POST"])
@user_required
def save_watch_progress(movie_id: int):
    user = get_current_user()
    if _public_movie(movie_id) is None:
        return jsonify({"error": "not found"}), 404
    data = request.get_json(silent=True) or {}
    try:
        progress = max(0, int(data.get("progress_seconds", 0)))
        duration = data.get("duration_seconds")
        duration = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        return jsonify({"error": "invalid data"}), 400
    completed = bool(data.get("completed")) or (duration and progress >= max(0, duration - 5))
    entry = db.session.scalar(select(WatchHistory).where(WatchHistory.user_id == user.id, WatchHistory.movie_id == movie_id))
    if not entry:
        entry = WatchHistory(user_id=user.id, movie_id=movie_id, last_watched_at=_now_str())
        db.session.add(entry)
    entry.progress_seconds = progress
    entry.duration_seconds = duration
    entry.completed = completed
    entry.last_watched_at = _now_str()
    db.session.commit()
    return jsonify({"ok": True})


@main.route("/profile/edit", methods=["GET", "POST"])
@user_required
def edit_profile():
    user = get_current_user()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", username):
            flash("Username must be 3 to 32 characters using letters, numbers or underscores.", "error")
            return render_template("profile_edit.html", user=user)
        if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            flash("Please enter a valid email address.", "error")
            return render_template("profile_edit.html", user=user)
        existing = db.session.scalar(select(User).where(or_(User.username == username, User.email == email), User.id != user.id))
        if existing:
            flash("Username or email is already in use.", "error")
            return render_template("profile_edit.html", user=user)
        if email != user.email:
            user.email_verified = False
        user.username = username
        user.email = email
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("Username or email is already in use.", "error")
            return render_template("profile_edit.html", user=user)
        flash("Profile updated.", "success")
        return redirect(url_for("main.profile"))
    return render_template("profile_edit.html", user=user)


@main.route("/profile/change-password", methods=["POST"])
@user_required
def change_password():
    user = get_current_user()
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    if not check_password_hash(user.password_hash, current_password):
        flash("Current password is incorrect.", "error")
        return redirect(url_for("main.edit_profile"))
    if len(new_password) < 12 or len(new_password) > 128:
        flash("Password must be between 12 and 128 characters.", "error")
        return redirect(url_for("main.edit_profile"))
    user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    flash("Password changed successfully.", "success")
    return redirect(url_for("main.profile"))


@main.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    reset_link = None
    if request.method == "POST":
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
        if _rate_limited(f"forgot:{ip}", 5, 300):
            flash("Too many requests. Please try again later.", "error")
            return render_template("forgot_password.html"), 429
        email = request.form.get("email", "").strip()
        user = db.session.scalar(select(User).where(User.email == email))
        if user:
            token = _new_token()
            db.session.add(PasswordResetToken(user_id=user.id, token=token, expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")))
            db.session.commit()
            reset_link = url_for("main.reset_password", token=token, _external=True)
            current_app.logger.info("Password reset link generated for user_id=%s", user.id)
        flash("If an account exists for that email, a reset link has been generated.", "success")
    return render_template("forgot_password.html", reset_link=reset_link)


@main.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    rec = db.session.scalar(select(PasswordResetToken).where(PasswordResetToken.token == token))
    if not rec or rec.used_at:
        flash("This reset link is invalid or has already been used.", "error")
        return redirect(url_for("main.forgot_password"))
    if rec.expires_at < _now_str():
        flash("This reset link has expired.", "error")
        return redirect(url_for("main.forgot_password"))
    user = db.session.get(User, rec.user_id)
    if not user:
        flash("Account not found.", "error")
        return redirect(url_for("main.forgot_password"))
    if request.method == "POST":
        password = request.form.get("password", "")
        if len(password) < 12 or len(password) > 128:
            flash("Password must be between 12 and 128 characters.", "error")
            return render_template("reset_password.html")
        user.password_hash = generate_password_hash(password)
        rec.used_at = _now_str()
        db.session.commit()
        flash("Password reset successful. Please log in.", "success")
        return redirect(url_for("main.login"))
    return render_template("reset_password.html")


@main.route("/verify-email/<token>")
@user_required
def verify_email(token: str):
    rec = db.session.scalar(select(EmailVerificationToken).where(EmailVerificationToken.token == token))
    if not rec or rec.used_at or rec.expires_at < _now_str():
        flash("Verification link is invalid or expired.", "error")
        return redirect(url_for("main.profile"))
    user = get_current_user()
    if rec.user_id != user.id:
        abort(403)
    user.email_verified = True
    rec.used_at = _now_str()
    db.session.commit()
    flash("Email verified.", "success")
    return redirect(url_for("main.profile"))


@main.route("/admin/users")
@admin_required
def admin_users():
    users = db.session.scalars(select(User).order_by(User.created_at.desc())).all()
    return render_template("admin_users.html", users=users)


@main.route("/admin/users/<int:user_id>/toggle-active", methods=["POST"])
@admin_required
def admin_toggle_user_active(user_id: int):
    actor = get_current_user()
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if user.id == actor.id:
        flash("You cannot suspend your own account.", "error")
        return redirect(url_for("main.admin_users"))
    user.is_active = not bool(getattr(user, "is_active", True))
    _record_admin_action("user.active_toggled", "user", user.id)
    db.session.commit()
    flash("User status updated.", "success")
    return redirect(url_for("main.admin_users"))


@main.route("/admin/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    keys = [
        "site_name", "contact_email", "contact_info", "announcement", "maintenance_mode",
        "ads_enabled", "ads_config", "ads_head_code", "ads_home_banner", "ads_incontent", "ads_movie_detail"
    ]
    if request.method == "POST":
        for key in keys:
            val = (request.form.get(key) or "").strip()
            row = db.session.get(Setting, key)
            if row is None:
                row = Setting(key=key, value=val)
                db.session.add(row)
            else:
                row.value = val
        _record_admin_action("settings.updated", "setting", None)
        db.session.commit()
        flash("Settings saved.", "success")
        return redirect(url_for("main.admin_settings"))
    settings = {k: (db.session.get(Setting, k).value if db.session.get(Setting, k) else "") for k in keys}
    return render_template("admin_settings.html", settings=settings)


@main.route("/admin/advertising")
@admin_required
def admin_advertising():
    return render_template("admin_ads.html")


@main.route("/admin/analytics")
@admin_required
def admin_analytics():
    stats = {
        "movies": db.session.scalar(select(func.count(Movie.id))) or 0,
        "published": db.session.scalar(select(func.count(Movie.id)).select_from(Movie).join(MovieRights).where(MovieRights.published.is_(True), MovieRights.rights_verified.is_(True))) or 0,
        "users": db.session.scalar(select(func.count(User.id))) or 0,
        "views": db.session.scalar(select(func.count(MovieView.id))) or 0,
    }
    view_counts = select(MovieView.movie_id, func.count(MovieView.id).label("c")).group_by(MovieView.movie_id).subquery()
    popular_rows = db.session.execute(select(Movie, view_counts.c.c).join(view_counts, view_counts.c.movie_id == Movie.id).order_by(view_counts.c.c.desc()).limit(10)).all()
    popular = [(row[0], row[1]) for row in popular_rows]
    return render_template("admin_analytics.html", stats=stats, popular=popular)


@main.route("/admin/import-metadata")
@admin_required
def admin_import_metadata():
    query = request.args.get("q", "").strip()
    results = []
    error = None
    if query:
        try:
            data = tmdb_search_movies(query, page=1)
            results = data.get("results") or []
        except (MetadataConfigError, MetadataProviderError) as e:
            error = str(e)
    return render_template("admin_import_metadata.html", query=query, results=results, error=error)


@main.route("/admin/import-metadata/<int:tmdb_id>", methods=["POST"])
@admin_required
def admin_import_metadata_item(tmdb_id: int):
    try:
        data = tmdb_get_movie(tmdb_id)
        mapped = map_tmdb_movie(data)
    except (MetadataConfigError, MetadataProviderError) as e:
        flash(str(e), "error")
        return redirect(url_for("main.admin_import_metadata"))
    # Avoid obvious duplicates by title+year when possible
    existing = db.session.scalar(select(Movie).where(Movie.title == mapped["title"], Movie.release_year == mapped.get("release_year")))
    if existing:
        flash("A movie with this title/year already exists. Opening it for review.", "success")
        return redirect(url_for("main.edit_admin_movie", movie_id=existing.id))
    movie = Movie(
        title=mapped["title"] or "Untitled",
        description=mapped.get("description"),
        release_year=mapped.get("release_year"),
        genre=mapped.get("genre"),
        director=mapped.get("director"),
        language=mapped.get("language"),
        rating=mapped.get("rating"),
        poster_url=mapped.get("poster_url"),
        backdrop_url=mapped.get("backdrop_url"),
        trailer_url=mapped.get("trailer_url"),
        availability="Restricted",
        created_at=_now_str(),
        is_featured=False,
    )
    db.session.add(movie)
    db.session.flush()
    db.session.add(MovieDetails(movie=movie, runtime_minutes=mapped.get("runtime_minutes"), cast_members=mapped.get("cast_members")))
    # Imported metadata only: unpublished, no verified rights/distribution permission.
    db.session.add(MovieRights(movie=movie, rights_verified=False, streaming_allowed=False, download_allowed=False, published=False))
    _record_admin_action("movie.imported_metadata", "movie", movie.id)
    db.session.commit()
    flash("Metadata imported as an unpublished draft. Review details, add documented rights, and publish only if you are authorised. " + (mapped.get("attribution") or ""), "success")
    return redirect(url_for("main.edit_admin_movie", movie_id=movie.id))


@main.app_errorhandler(404)
def not_found_error(error):
    return render_template("404.html"), 404


@main.app_errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template("500.html"), 500


@main.app_context_processor
def inject_globals():
    user = get_current_user()
    ads_keys = ["ads_enabled", "ads_head_code", "ads_home_banner", "ads_incontent", "ads_movie_detail"]
    ads = {}
    for k in ads_keys:
        row = db.session.get(Setting, k)
        ads[k] = row.value if row and row.value else ""
    return {
        "current_user": user,
        "is_admin": bool(user and user.is_admin),
        "featured_movie": get_featured_movie(),
        "site_ads": ads,
        "ads_on": ads.get("ads_enabled") == "on",
    }


@main.after_app_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if current_app.config["APP_ENV"] == "production":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@main.route("/health")
def health():
    try:
        db.session.execute(select(1))
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.error("Database health check failed.")
        return {"status": "unavailable"}, 503
    return {"status": "ok"}, 200


@main.route("/genre/<string:genre_name>")
def genre_page(genre_name: str):
    try:
        page = _requested_page()
    except ValueError as error:
        abort(400, description=str(error))
    query = (
        _published_movies_query()
        .where(Movie.genre == genre_name)
        .order_by(Movie.rating.desc())
    )
    pagination = db.paginate(query, page=page, per_page=MOVIE_PAGE_SIZE)
    return render_template(
        "movies.html",
        movies=pagination.items,
        pagination=pagination,
        pagination_args={
            key: value for key, value in request.args.items() if key != "page"
        },
        genres=get_genres(),
        current_query=genre_name,
        current_sort="rated",
        genre_name=genre_name,
    )
