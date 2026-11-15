from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

import click
from flask import current_app
from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    inspect,
)
from sqlalchemy.engine import make_url
from sqlalchemy.sql import insert

from .extensions import db


class Movie(db.Model):
    __tablename__ = "movies"

    id = db.Column(Integer, primary_key=True)
    title = db.Column(String(255), nullable=False)
    release_year = db.Column(Integer)
    genre = db.Column(String(100))
    description = db.Column(Text)
    director = db.Column(String(255))
    language = db.Column(String(100))
    rating = db.Column(Float)
    popularity = db.Column(Float)
    availability = db.Column(String(100))
    poster_url = db.Column(Text)
    backdrop_url = db.Column(Text)
    trailer_url = db.Column(Text)
    movie_url = db.Column(Text)
    keywords = db.Column(Text)
    created_at = db.Column(String(32))
    is_featured = db.Column(Boolean, nullable=False, default=False)


class MovieDetails(db.Model):
    __tablename__ = "movie_details"

    movie_id = db.Column(
        Integer, ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True
    )
    runtime_minutes = db.Column(Integer)
    cast_members = db.Column(Text)
    movie = db.relationship(
        "Movie", backref=db.backref("details", uselist=False, cascade="all, delete-orphan")
    )


class MovieRights(db.Model):
    __tablename__ = "movie_rights"

    movie_id = db.Column(
        Integer, ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True
    )
    rights_holder = db.Column(String(255))
    license_reference = db.Column(String(255))
    territories = db.Column(Text)
    license_start = db.Column(Date)
    license_expiry = db.Column(Date)
    rights_verified = db.Column(Boolean, nullable=False, default=False)
    streaming_allowed = db.Column(Boolean, nullable=False, default=False)
    download_allowed = db.Column(Boolean, nullable=False, default=False)
    published = db.Column(Boolean, nullable=False, default=False)
    movie = db.relationship(
        "Movie", backref=db.backref("rights", uselist=False, cascade="all, delete-orphan")
    )


class MovieAsset(db.Model):
    __tablename__ = "movie_assets"

    movie_id = db.Column(
        Integer, ForeignKey("movies.id", ondelete="CASCADE"), primary_key=True
    )
    poster_key = db.Column(String(255))
    trailer_key = db.Column(String(255))
    video_key = db.Column(String(255))
    poster_mime = db.Column(String(100))
    trailer_mime = db.Column(String(100))
    video_mime = db.Column(String(100))
    video_size = db.Column(Integer)
    movie = db.relationship(
        "Movie", backref=db.backref("assets", uselist=False, cascade="all, delete-orphan")
    )


class MovieView(db.Model):
    __tablename__ = "movie_views"

    id = db.Column(Integer, primary_key=True)
    movie_id = db.Column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False)
    viewed_at = db.Column(String(32), nullable=False)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(Integer, primary_key=True)
    actor_user_id = db.Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action = db.Column(String(64), nullable=False)
    entity_type = db.Column(String(64), nullable=False)
    entity_id = db.Column(Integer)
    created_at = db.Column(String(32), nullable=False)
    actor = db.relationship(
        "User",
        backref=db.backref("audit_logs", passive_deletes=True),
    )


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(Integer, primary_key=True)
    username = db.Column(String(32), nullable=False, unique=True)
    email = db.Column(String(254), nullable=False, unique=True)
    password_hash = db.Column(String(255), nullable=False)
    is_admin = db.Column(Boolean, nullable=False, default=False)
    created_at = db.Column(String(32))


class Watchlist(db.Model):
    __tablename__ = "watchlists"
    __table_args__ = (UniqueConstraint("user_id", "movie_id", name="uq_watchlist_user_movie"),)

    id = db.Column(Integer, primary_key=True)
    user_id = db.Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    movie_id = db.Column(Integer, ForeignKey("movies.id", ondelete="CASCADE"), nullable=False)
    created_at = db.Column(String(32))

    user = db.relationship("User", backref=db.backref("watchlists", cascade="all, delete-orphan"))
    movie = db.relationship("Movie", backref=db.backref("watchlist_entries", cascade="all, delete-orphan"))


class Setting(db.Model):
    __tablename__ = "settings"

    key = db.Column(String(100), primary_key=True)
    value = db.Column(Text)


def _sqlite_source_rows(source_path: Path) -> dict[str, list[dict[str, object]]]:
    required_tables = ("movies", "users", "watchlists", "settings")
    connection = sqlite3.connect(f"{source_path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        existing_tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing_tables = set(required_tables) - existing_tables
        if missing_tables:
            raise ValueError(
                "Legacy SQLite database is missing required tables: "
                + ", ".join(sorted(missing_tables))
            )
        unexpected_tables = existing_tables - set(required_tables) - {"sqlite_sequence"}
        if unexpected_tables:
            raise ValueError(
                "Legacy SQLite database contains unsupported tables: "
                + ", ".join(sorted(unexpected_tables))
            )
        for table in required_tables:
            source_columns = {
                row["name"] for row in connection.execute(f"PRAGMA table_info({table})")
            }
            target_columns = set(db.metadata.tables[table].columns.keys())
            if source_columns != target_columns:
                raise ValueError(
                    f"Legacy table '{table}' does not match the supported schema."
                )
        return {
            table: [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
            for table in required_tables
        }
    finally:
        connection.close()


def _target_sqlite_path() -> Path | None:
    target_url = make_url(current_app.config["SQLALCHEMY_DATABASE_URI"])
    if target_url.get_backend_name() != "sqlite" or target_url.database in (None, "", ":memory:"):
        return None
    return Path(target_url.database).expanduser().resolve()


def import_legacy_sqlite(source: str | Path) -> dict[str, int]:
    source_path = Path(source).expanduser().resolve(strict=True)
    if not source_path.is_file():
        raise ValueError("The legacy SQLite source must be a regular file.")

    target_path = _target_sqlite_path()
    if target_path is not None and source_path == target_path:
        raise ValueError("The source and destination databases must be different files.")
    if db.engine.dialect.name not in {"mysql", "sqlite"}:
        raise ValueError("The destination database must use MySQL or SQLite.")

    rows_by_table = _sqlite_source_rows(source_path)
    inspector = inspect(db.engine)
    target_tables = set(inspector.get_table_names())
    missing_target_tables = set(db.metadata.tables) - target_tables
    if missing_target_tables:
        raise ValueError(
            "The destination schema is not initialized. Run the database migrations first."
        )
    unexpected_target_tables = target_tables - set(db.metadata.tables) - {"alembic_version"}
    if unexpected_target_tables:
        raise ValueError(
            "The destination database contains unsupported tables: "
            + ", ".join(sorted(unexpected_target_tables))
        )

    for movie in rows_by_table["movies"]:
        movie_url = movie.get("movie_url")
        hostname = urlsplit(movie_url).hostname if isinstance(movie_url, str) else None
        if hostname and (hostname == "w3schools.com" or hostname.endswith(".w3schools.com")):
            movie["movie_url"] = None

    with db.engine.begin() as connection:
        for table_name in db.metadata.tables:
            if connection.execute(
                db.metadata.tables[table_name].select().limit(1)
            ).first():
                raise ValueError(
                    f"Destination table '{table_name}' is not empty; import was not started."
                )
        for table_name in ("movies", "users", "watchlists", "settings"):
            table = db.metadata.tables[table_name]
            values = [
                {key: value for key, value in row.items() if key in table.columns}
                for row in rows_by_table[table_name]
            ]
            if values:
                connection.execute(insert(table), values)

    return {table_name: len(rows) for table_name, rows in rows_by_table.items()}


@click.command("import-legacy-sqlite")
@click.argument("source", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def import_legacy_sqlite_command(source: Path) -> None:
    """Import an existing SQLite database into the configured empty database."""
    try:
        counts = import_legacy_sqlite(source)
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    click.echo(
        "Imported "
        + ", ".join(f"{count} {table}" for table, count in counts.items())
        + "."
    )
