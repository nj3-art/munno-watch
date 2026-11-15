"""add reviews and ratings

Revision ID: 5d2e3f4a5b6c
Revises: 4c1f2d8a9b10
Create Date: 2026-11-15 18:00:00.000000

"""
from alembic import context, op
import sqlalchemy as sa


revision = '5d2e3f4a5b6c'
down_revision = '4c1f2d8a9b10'
branch_labels = None
depends_on = None


def _has_table(name):
    return name in set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    if not _has_table("reviews"):
        op.create_table(
            "reviews",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("movie_id", sa.Integer(), nullable=False),
            sa.Column("rating", sa.Integer(), nullable=True),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("created_at", sa.String(length=32), nullable=False),
            sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "movie_id", name="uq_review_user_movie"),
        )


def downgrade():
    if _has_table("reviews"):
        op.drop_table("reviews")
