"""add user engagement and auth tables

Revision ID: 4c1f2d8a9b10
Revises: 3f64a6c40e62
Create Date: 2026-11-15 16:30:00.000000

"""
from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '4c1f2d8a9b10'
down_revision = '3f64a6c40e62'
branch_labels = None
depends_on = None


def _has_table(name):
    return name in set(sa.inspect(op.get_bind()).get_table_names())


def _has_column(table, column):
    if not _has_table(table):
        return False
    return column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _has_table("users"):
        cols = {c["name"] for c in insp.get_columns("users")}
        with op.batch_alter_table("users") as batch:
            if "is_active" not in cols:
                batch.add_column(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
            if "email_verified" not in cols:
                batch.add_column(sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()))

    if not _has_table("favourites"):
        op.create_table(
            "favourites",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("movie_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.String(length=32), nullable=True),
            sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "movie_id", name="uq_favourite_user_movie"),
        )

    if not _has_table("watch_history"):
        op.create_table(
            "watch_history",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("movie_id", sa.Integer(), nullable=False),
            sa.Column("progress_seconds", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duration_seconds", sa.Integer(), nullable=True),
            sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("last_watched_at", sa.String(length=32), nullable=False),
            sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "movie_id", name="uq_watch_history_user_movie"),
        )

    if not _has_table("password_reset_tokens"):
        op.create_table(
            "password_reset_tokens",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("token", sa.String(length=128), nullable=False),
            sa.Column("expires_at", sa.String(length=32), nullable=False),
            sa.Column("used_at", sa.String(length=32), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token"),
        )

    if not _has_table("email_verification_tokens"):
        op.create_table(
            "email_verification_tokens",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("token", sa.String(length=128), nullable=False),
            sa.Column("expires_at", sa.String(length=32), nullable=False),
            sa.Column("used_at", sa.String(length=32), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token"),
        )


def downgrade():
    for table in ["email_verification_tokens", "password_reset_tokens", "watch_history", "favourites"]:
        if _has_table(table):
            op.drop_table(table)
    if _has_table("users"):
        cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("users")}
        with op.batch_alter_table("users") as batch:
            if "email_verified" in cols:
                batch.drop_column("email_verified")
            if "is_active" in cols:
                batch.drop_column("is_active")
