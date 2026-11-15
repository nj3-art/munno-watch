from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from flask import Blueprint, abort, current_app, flash, has_app_context, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .auth import admin_required, get_current_user, is_in_watchlist, is_safe_redirect_target, user_required
from .database import get_db


main = Blueprint("main", __name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def ensure_db(database_path: Optional[str] = None) -> None:
    if database_path is None:
        database_path = (
            current_app.config["DATABASE_PATH"]
            if has_app_context()
            else str(PROJECT_ROOT / "cinezone.db")
        )
    db = sqlite3.connect(database_path)
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            release_year INTEGER,
            genre TEXT,
            description TEXT,
            director TEXT,
            language TEXT,
            rating REAL,
            popularity REAL,
            availability TEXT,
            poster_url TEXT,
            backdrop_url TEXT,
            trailer_url TEXT,
            movie_url TEXT,
            keywords TEXT,
            created_at TEXT,
            is_featured INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS watchlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            movie_id INTEGER NOT NULL,
            created_at TEXT,
            UNIQUE(user_id, movie_id)
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """
    )

    if db.execute("SELECT COUNT(*) FROM movies").fetchone()[0] == 0:
        seed_movies(db)

    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed_admin_user(db)

    if db.execute("SELECT COUNT(*) FROM settings WHERE key = 'featured_movie_id'").fetchone()[0] == 0:
        featured_id = db.execute("SELECT id FROM movies ORDER BY popularity DESC LIMIT 1").fetchone()
        if featured_id:
            db.execute(
                "INSERT INTO settings (key, value) VALUES ('featured_movie_id', ?)",
                (str(featured_id["id"]),),
            )

    db.commit()
    db.close()


def seed_admin_user(db: sqlite3.Connection) -> None:
    admin_password = os.environ.get("CINEZONE_ADMIN_PASSWORD")
    if not admin_password:
        return
    username = os.environ.get("CINEZONE_ADMIN_USERNAME", "admin")
    email = os.environ.get("CINEZONE_ADMIN_EMAIL", "admin@cinezone.app")
    if len(admin_password) < 12 or len(admin_password) > 128:
        raise RuntimeError("CINEZONE_ADMIN_PASSWORD must be between 12 and 128 characters.")
    if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", username):
        raise RuntimeError("CINEZONE_ADMIN_USERNAME must be 3 to 32 letters, numbers or underscores.")
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise RuntimeError("CINEZONE_ADMIN_EMAIL must be a valid email address.")
    db.execute(
        """
        INSERT INTO users (username, email, password_hash, is_admin, created_at)
        VALUES (?, ?, ?, 1, ?)
        """,
        (username, email, generate_password_hash(admin_password), datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
    )


def seed_movies(db: sqlite3.Connection) -> None:
    movie_rows = [
        {
            "title": "Neon Horizon",
            "release_year": 2024,
            "genre": "Science Fiction",
            "description": "A rogue pilot uncovers a forgotten star map that could reshape humanity's future, forcing her to choose between law and freedom.",
            "director": "Alicia Moreno",
            "language": "English",
            "rating": 8.9,
            "popularity": 97.4,
            "availability": "Streaming",
            "poster_url": "https://images.unsplash.com/photo-1517604931442-7e0c8ed2963c?auto=format&fit=crop&w=900&q=80",
            "backdrop_url": "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=1400&q=80",
            "trailer_url": "https://www.youtube.com/embed/ysz5S6PUM-U",
            "movie_url": "https://www.w3schools.com/html/mov_bbb.mp4",
            "keywords": "space, sci-fi, pilot, galaxy, future",
            "created_at": "2024-11-16 12:00:00",
        },
        {
            "title": "Velvet Echo",
            "release_year": 2023,
            "genre": "Drama",
            "description": "A gifted composer returns home to rebuild her late mother's theatre and rediscovers the music that changed everything.",
            "director": "Katherine Frost",
            "language": "English",
            "rating": 8.7,
            "popularity": 88.2,
            "availability": "Premium",
            "poster_url": "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?auto=format&fit=crop&w=900&q=80",
            "backdrop_url": "https://images.unsplash.com/photo-1497032628192-86f99bcd76bc?auto=format&fit=crop&w=1400&q=80",
            "trailer_url": "https://www.youtube.com/embed/ScMzIvxBSi4",
            "movie_url": "https://www.w3schools.com/html/movie.mp4",
            "keywords": "music, theater, family, drama, heritage",
            "created_at": "2024-10-09 09:30:00",
        },
        {
            "title": "Crimson Ridge",
            "release_year": 2022,
            "genre": "Action",
            "description": "An elite ranger and an ex-con team up to stop a cartel from triggering a siege on the last border town.",
            "director": "Daniel Cole",
            "language": "English",
            "rating": 8.6,
            "popularity": 91.8,
            "availability": "Streaming",
            "poster_url": "https://images.unsplash.com/photo-1513106580091-1d82408b8cd6?auto=format&fit=crop&w=900&q=80",
            "backdrop_url": "https://images.unsplash.com/photo-1524985069026-dd778a71c7b4?auto=format&fit=crop&w=1400&q=80",
            "trailer_url": "https://www.youtube.com/embed/1_hS7D0hv4g",
            "movie_url": "https://www.w3schools.com/html/mov_bbb.mp4",
            "keywords": "action, thriller, cartel, border, survival",
            "created_at": "2024-09-15 11:00:00",
        },
        {
            "title": "Aurora Lights",
            "release_year": 2024,
            "genre": "Animation",
            "description": "A city of floating lanterns hides a magical conflict between the sky folk and the last human explorer.",
            "director": "Sora Nguyen",
            "language": "Japanese",
            "rating": 9.1,
            "popularity": 96.1,
            "availability": "Streaming",
            "poster_url": "https://images.unsplash.com/photo-1515879218367-8466d910aaa4?auto=format&fit=crop&w=900&q=80",
            "backdrop_url": "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1400&q=80",
            "trailer_url": "https://www.youtube.com/embed/2D8w2UfX5UQ",
            "movie_url": "https://www.w3schools.com/html/movie.mp4",
            "keywords": "animation, fantasy, lanterns, sky, magical",
            "created_at": "2024-11-11 15:20:00",
        },
        {
            "title": "Northern Ghosts",
            "release_year": 2021,
            "genre": "Horror",
            "description": "An isolated lighthouse keeper confronts the truth behind decades of disappearances in a frozen inlet.",
            "director": "Mila Hamilton",
            "language": "English",
            "rating": 8.2,
            "popularity": 80.9,
            "availability": "Premium",
            "poster_url": "https://images.unsplash.com/photo-1504384308090-c894fdcc538d?auto=format&fit=crop&w=900&q=80",
            "backdrop_url": "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=1400&q=80",
            "trailer_url": "https://www.youtube.com/embed/C0BMx-qxsP4",
            "movie_url": "https://www.w3schools.com/html/mov_bbb.mp4",
            "keywords": "horror, lighthouse, mystery, winter, ghost",
            "created_at": "2024-08-20 13:15:00",
        },
        {
            "title": "The Last Orchard",
            "release_year": 2020,
            "genre": "Romance",
            "description": "Two childhood friends reopen an abandoned orchard and discover the love story they never got to live.",
            "director": "Sophie Kim",
            "language": "French",
            "rating": 8.5,
            "popularity": 84.7,
            "availability": "Streaming",
            "poster_url": "https://images.unsplash.com/photo-1497032628192-86f99bcd76bc?auto=format&fit=crop&w=900&q=80",
            "backdrop_url": "https://images.unsplash.com/photo-1478720568477-152d9b164e26?auto=format&fit=crop&w=1400&q=80",
            "trailer_url": "https://www.youtube.com/embed/dQw4w9WgXcQ",
            "movie_url": "https://www.w3schools.com/html/movie.mp4",
            "keywords": "romance, orchard, love, reunion, heart",
            "created_at": "2024-07-03 12:15:00",
        },
        {
            "title": "Signal Bloom",
            "release_year": 2023,
            "genre": "Mystery",
            "description": "A citywide blackout reveals a hidden network of messages from the future and a missing journalist's final clue.",
            "director": "Evan Shah",
            "language": "English",
            "rating": 8.4,
            "popularity": 82.5,
            "availability": "Premium",
            "poster_url": "https://images.unsplash.com/photo-1522202176988-66273c2fd55f?auto=format&fit=crop&w=900&q=80",
            "backdrop_url": "https://images.unsplash.com/photo-1531297484001-80022131f5a1?auto=format&fit=crop&w=1400&q=80",
            "trailer_url": "https://www.youtube.com/embed/ysz5S6PUM-U",
            "movie_url": "https://www.w3schools.com/html/mov_bbb.mp4",
            "keywords": "future, clues, mystery, blackout, suspense",
            "created_at": "2024-09-09 10:45:00",
        },
        {
            "title": "Kingdom of Rain",
            "release_year": 2024,
            "genre": "Fantasy",
            "description": "When the monsoon stops, a young healer must travel across a mythic kingdom to restore a dying storm god.",
            "director": "Priya Nair",
            "language": "Hindi",
            "rating": 8.8,
            "popularity": 93.7,
            "availability": "Streaming",
            "poster_url": "https://images.unsplash.com/photo-1485846234645-a62644f84728?auto=format&fit=crop&w=900&q=80",
            "backdrop_url": "https://images.unsplash.com/photo-1516035069371-29a1b244cc32?auto=format&fit=crop&w=1400&q=80",
            "trailer_url": "https://www.youtube.com/embed/ScMzIvxBSi4",
            "movie_url": "https://www.w3schools.com/html/movie.mp4",
            "keywords": "fantasy, storm, kingdom, myth, healer",
            "created_at": "2024-11-03 16:00:00",
        },
        {
            "title": "Copper Harbor",
            "release_year": 2022,
            "genre": "Crime",
            "description": "A dockside investigator tracks a string of smuggled relics that point toward a conspiracy inside the mayor's office.",
            "director": "Amelia Ross",
            "language": "English",
            "rating": 8.3,
            "popularity": 79.5,
            "availability": "Free",
            "poster_url": "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=900&q=80",
            "backdrop_url": "https://images.unsplash.com/photo-1504384308090-c894fdcc538d?auto=format&fit=crop&w=1400&q=80",
            "trailer_url": "https://www.youtube.com/embed/1_hS7D0hv4g",
            "movie_url": "https://www.w3schools.com/html/mov_bbb.mp4",
            "keywords": "crime, conspiracy, relics, harbor, detective",
            "created_at": "2024-05-20 11:50:00",
        },
        {
            "title": "Paper Skies",
            "release_year": 2021,
            "genre": "Comedy",
            "description": "A novice magician must save his family's struggling theatre by staging a festival no one will forget.",
            "director": "Luca Palmer",
            "language": "Spanish",
            "rating": 7.9,
            "popularity": 76.1,
            "availability": "Free",
            "poster_url": "https://images.unsplash.com/photo-1524985069026-dd778a71c7b4?auto=format&fit=crop&w=900&q=80",
            "backdrop_url": "https://images.unsplash.com/photo-1517604931442-7e0c8ed2963c?auto=format&fit=crop&w=1400&q=80",
            "trailer_url": "https://www.youtube.com/embed/C0BMx-qxsP4",
            "movie_url": "https://www.w3schools.com/html/movie.mp4",
            "keywords": "comedy, theatre, magic, festival, family",
            "created_at": "2024-04-18 19:30:00",
        },
    ]

    for item in movie_rows:
        db.execute(
            """
            INSERT INTO movies (
                title, release_year, genre, description, director, language, rating,
                popularity, availability, poster_url, backdrop_url, trailer_url,
                movie_url, keywords, created_at, is_featured
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                item["title"],
                item["release_year"],
                item["genre"],
                item["description"],
                item["director"],
                item["language"],
                item["rating"],
                item["popularity"],
                item["availability"],
                item["poster_url"],
                item["backdrop_url"],
                item["trailer_url"],
                item["movie_url"],
                item["keywords"],
                item["created_at"],
            ),
        )


def get_genres() -> List[str]:
    rows = get_db().execute("SELECT DISTINCT genre FROM movies ORDER BY genre").fetchall()
    return [row["genre"] for row in rows]


def get_featured_movie() -> Optional[sqlite3.Row]:
    db = get_db()
    setting_row = db.execute("SELECT value FROM settings WHERE key = 'featured_movie_id'").fetchone()
    if setting_row:
        movie_id = setting_row["value"]
        movie = db.execute("SELECT * FROM movies WHERE id = ?", (movie_id,)).fetchone()
        if movie:
            return movie
    return db.execute("SELECT * FROM movies ORDER BY popularity DESC LIMIT 1").fetchone()


def get_movie(movie_id: int) -> Optional[sqlite3.Row]:
    return get_db().execute("SELECT * FROM movies WHERE id = ?", (movie_id,)).fetchone()


@main.route("/")
def home():
    db = get_db()
    featured = get_featured_movie()
    trending = db.execute("SELECT * FROM movies ORDER BY popularity DESC LIMIT 8").fetchall()
    latest = db.execute("SELECT * FROM movies ORDER BY release_year DESC LIMIT 8").fetchall()
    popular = db.execute("SELECT * FROM movies ORDER BY popularity DESC LIMIT 8").fetchall()
    top_rated = db.execute("SELECT * FROM movies ORDER BY rating DESC LIMIT 8").fetchall()
    recommended = db.execute(
        "SELECT * FROM movies WHERE genre = ? ORDER BY rating DESC LIMIT 6",
        (featured["genre"],) if featured else ("Science Fiction",),
    ).fetchall()
    recently_added = db.execute("SELECT * FROM movies ORDER BY created_at DESC LIMIT 8").fetchall()
    editors_picks = db.execute("SELECT * FROM movies WHERE rating >= 8.5 ORDER BY popularity DESC LIMIT 6").fetchall()
    collections = [
        {"name": "Action", "image": "https://images.unsplash.com/photo-1517604931442-7e0c8ed2963c?auto=format&fit=crop&w=800&q=80"},
        {"name": "Drama", "image": "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?auto=format&fit=crop&w=800&q=80"},
        {"name": "Science Fiction", "image": "https://images.unsplash.com/photo-1531297484001-80022131f5a1?auto=format&fit=crop&w=800&q=80"},
        {"name": "Fantasy", "image": "https://images.unsplash.com/photo-1516035069371-29a1b244cc32?auto=format&fit=crop&w=800&q=80"},
    ]
    genres = get_genres()
    return render_template(
        "index.html",
        featured=featured,
        sections=[
            {"title": "Trending Movies", "movies": trending},
            {"title": "Latest Releases", "movies": latest},
            {"title": "Popular Movies", "movies": popular},
            {"title": "Top Rated Movies", "movies": top_rated},
            {"title": "Recommended For You", "movies": recommended},
            {"title": "Recently Added", "movies": recently_added},
            {"title": "Editor's Picks", "movies": editors_picks},
        ],
        collections=collections,
        genres=genres,
    )


@main.route("/movies")
def movies():
    db = get_db()
    query = "SELECT * FROM movies WHERE 1=1"
    params: List[Any] = []
    search_term = request.args.get("q", "").strip()
    genre = request.args.get("genre", "").strip()
    release_year = request.args.get("year", "").strip()
    language = request.args.get("language", "").strip()
    rating = request.args.get("rating", "").strip()
    availability = request.args.get("availability", "").strip()
    sort = request.args.get("sort", "newest")

    if search_term:
        query += " AND (title LIKE ? OR genre LIKE ? OR description LIKE ? OR keywords LIKE ? OR director LIKE ?)"
        like_term = f"%{search_term}%"
        params.extend([like_term, like_term, like_term, like_term, like_term])

    if genre:
        query += " AND genre = ?"
        params.append(genre)

    if release_year:
        try:
            year = int(release_year)
        except ValueError:
            abort(400, description="Release year must be a whole number.")
        if year < 1888 or year > datetime.now(timezone.utc).year + 5:
            abort(400, description="Release year is outside the supported range.")
        query += " AND release_year = ?"
        params.append(year)

    if language:
        query += " AND language = ?"
        params.append(language)

    if rating:
        try:
            minimum_rating = float(rating)
        except ValueError:
            abort(400, description="Rating must be a number.")
        if not 0 <= minimum_rating <= 10:
            abort(400, description="Rating must be between 0 and 10.")
        query += " AND rating >= ?"
        params.append(minimum_rating)

    if availability:
        query += " AND availability = ?"
        params.append(availability)

    sort_options = {
        "newest": "release_year DESC, popularity DESC",
        "oldest": "release_year ASC, popularity DESC",
        "popular": "popularity DESC, rating DESC",
        "rated": "rating DESC, popularity DESC",
        "alpha": "title ASC",
    }
    query += " ORDER BY " + sort_options.get(sort, sort_options["newest"])

    results = db.execute(query, params).fetchall()
    return render_template(
        "movies.html",
        movies=results,
        genres=get_genres(),
        current_query=search_term,
        current_sort=sort,
    )


@main.route("/movie/<int:movie_id>")
def movie_detail(movie_id: int):
    movie = get_movie(movie_id)
    if movie is None:
        flash("Movie not found.", "error")
        return redirect(url_for("main.movies"))

    related = get_db().execute(
        "SELECT * FROM movies WHERE genre = ? AND id != ? ORDER BY rating DESC LIMIT 4",
        (movie["genre"], movie_id),
    ).fetchall()
    user = get_current_user()
    in_watchlist = bool(user and is_in_watchlist(user["id"], movie_id))
    return render_template("movie.html", movie=movie, related=related, in_watchlist=in_watchlist)


@main.route("/watch/<int:movie_id>")
def watch_movie(movie_id: int):
    movie = get_movie(movie_id)
    if movie is None:
        flash("Movie not found.", "error")
        return redirect(url_for("main.movies"))
    return render_template("watch.html", movie=movie)


@main.route("/toggle-watchlist/<int:movie_id>", methods=["POST"])
@user_required
def toggle_watchlist(movie_id: int):
    user = get_current_user()
    db = get_db()
    if get_movie(movie_id) is None:
        abort(404)
    if is_in_watchlist(user["id"], movie_id):
        db.execute("DELETE FROM watchlists WHERE user_id = ? AND movie_id = ?", (user["id"], movie_id))
        flash("Removed from your watchlist.", "success")
    else:
        db.execute(
            "INSERT INTO watchlists (user_id, movie_id, created_at) VALUES (?, ?, ?)",
            (user["id"], movie_id, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
        )
        flash("Added to your watchlist.", "success")
    db.commit()
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

        db = get_db()
        if db.execute("SELECT 1 FROM users WHERE username = ? OR email = ?", (username, email)).fetchone():
            flash("A user with that username or email already exists.", "error")
            return render_template("register.html")

        db.execute(
            "INSERT INTO users (username, email, password_hash, is_admin, created_at) VALUES (?, ?, ?, 0, ?)",
            (username, email, generate_password_hash(password), datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
        )
        db.commit()
        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("main.login"))

    return render_template("register.html")


@main.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute(
            "SELECT * FROM users WHERE username = ? OR email = ?",
            (username, username),
        ).fetchone()

        if not user or not check_password_hash(user["password_hash"], password):
            flash("Invalid username or password.", "error")
            return render_template("login.html")

        session.clear()
        session["user_id"] = user["id"]
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
    watchlist = get_db().execute(
        """
        SELECT m.* FROM movies m
        INNER JOIN watchlists w ON w.movie_id = m.id
        WHERE w.user_id = ?
        ORDER BY w.created_at DESC
        """,
        (user["id"],),
    ).fetchall()
    return render_template("profile.html", user=user, watchlist=watchlist)


@main.route("/admin", methods=["GET", "POST"])
@admin_required
def admin():
    db = get_db()
    if request.method == "POST":
        movie_id = request.form.get("featured_movie_id")
        if movie_id:
            db.execute(
                "INSERT INTO settings (key, value) VALUES ('featured_movie_id', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (movie_id,),
            )
            db.commit()
            flash("Featured movie updated successfully.", "success")

    movies = db.execute("SELECT * FROM movies ORDER BY title ASC").fetchall()
    current_featured = get_featured_movie()
    return render_template("admin.html", movies=movies, current_featured=current_featured)


@main.app_context_processor
def inject_globals():
    user = get_current_user()
    return {
        "current_user": user,
        "is_admin": bool(user and user["is_admin"] == 1),
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


@main.route("/genre/<string:genre_name>")
def genre_page(genre_name: str):
    movies = get_db().execute("SELECT * FROM movies WHERE genre = ? ORDER BY rating DESC", (genre_name,)).fetchall()
    return render_template("movies.html", movies=movies, genres=get_genres(), current_query=genre_name)
