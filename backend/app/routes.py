from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
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
from .models import (
    Movie,
    MovieAsset,
    MovieDetails,
    MovieRights,
    MovieView,
    Setting,
    User,
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

    results = db.session.scalars(query).all()
    return render_template(
        "movies.html",
        movies=results,
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
    db.session.add(
        MovieView(
            movie_id=movie.id,
            viewed_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        )
    )
    db.session.commit()
    has_video = bool(movie.assets and storage_has_key(movie.assets.video_key))
    can_stream = _content_allowed(movie, "stream")
    can_download = _content_allowed(movie, "download")
    return render_template(
        "movie.html",
        movie=movie,
        related=related,
        in_watchlist=in_watchlist,
        has_video=has_video,
        can_stream=can_stream,
        can_download=can_download,
    )


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
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db.session.scalar(
            select(User).where(or_(User.username == username, User.email == username))
        )

        if not user or not check_password_hash(user.password_hash, password):
            flash("Invalid username or password.", "error")
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
    return render_template(
        "admin.html",
        movies=movies,
        current_featured=current_featured,
        featured_options=featured_options,
        search=search,
        status_filter=status_filter,
        users=users,
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
        db.session.commit()
    flash("Movie is unpublished.", "success")
    return redirect(url_for("main.admin"))


@main.app_context_processor
def inject_globals():
    user = get_current_user()
    return {
        "current_user": user,
        "is_admin": bool(user and user.is_admin),
        "featured_movie": get_featured_movie(),
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
    movies = db.session.scalars(
        _published_movies_query()
        .where(Movie.genre == genre_name)
        .order_by(Movie.rating.desc())
    ).all()
    return render_template("movies.html", movies=movies, genres=get_genres(), current_query=genre_name)
