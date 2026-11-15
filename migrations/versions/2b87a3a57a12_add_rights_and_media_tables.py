"""add rights and media tables

Revision ID: 2b87a3a57a12
Revises: 55b61e8704a3
Create Date: 2026-11-15 14:02:10.098798

"""
from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2b87a3a57a12'
down_revision = '55b61e8704a3'
branch_labels = None
depends_on = None


def upgrade():
    existing_tables = (
        None
        if context.is_offline_mode()
        else set(sa.inspect(op.get_bind()).get_table_names())
    )
    if existing_tables is None or "movie_assets" not in existing_tables:
        op.create_table(
            "movie_assets",
            sa.Column("movie_id", sa.Integer(), nullable=False),
            sa.Column("poster_key", sa.String(length=255), nullable=True),
            sa.Column("trailer_key", sa.String(length=255), nullable=True),
            sa.Column("video_key", sa.String(length=255), nullable=True),
            sa.Column("poster_mime", sa.String(length=100), nullable=True),
            sa.Column("trailer_mime", sa.String(length=100), nullable=True),
            sa.Column("video_mime", sa.String(length=100), nullable=True),
            sa.Column("video_size", sa.Integer(), nullable=True),
            sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("movie_id"),
        )
    if existing_tables is None or "movie_details" not in existing_tables:
        op.create_table(
            "movie_details",
            sa.Column("movie_id", sa.Integer(), nullable=False),
            sa.Column("runtime_minutes", sa.Integer(), nullable=True),
            sa.Column("cast_members", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("movie_id"),
        )
    if existing_tables is None or "movie_rights" not in existing_tables:
        op.create_table(
            "movie_rights",
            sa.Column("movie_id", sa.Integer(), nullable=False),
            sa.Column("rights_holder", sa.String(length=255), nullable=True),
            sa.Column("license_reference", sa.String(length=255), nullable=True),
            sa.Column("territories", sa.Text(), nullable=True),
            sa.Column("license_start", sa.Date(), nullable=True),
            sa.Column("license_expiry", sa.Date(), nullable=True),
            sa.Column("rights_verified", sa.Boolean(), nullable=False),
            sa.Column("streaming_allowed", sa.Boolean(), nullable=False),
            sa.Column("download_allowed", sa.Boolean(), nullable=False),
            sa.Column("published", sa.Boolean(), nullable=False),
            sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("movie_id"),
        )
    if existing_tables is None or "movie_views" not in existing_tables:
        op.create_table(
            "movie_views",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("movie_id", sa.Integer(), nullable=False),
            sa.Column("viewed_at", sa.String(length=32), nullable=False),
            sa.ForeignKeyConstraint(["movie_id"], ["movies.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade():
    existing_tables = (
        None
        if context.is_offline_mode()
        else set(sa.inspect(op.get_bind()).get_table_names())
    )
    for table_name in ("movie_views", "movie_rights", "movie_details", "movie_assets"):
        if existing_tables is None or table_name in existing_tables:
            op.drop_table(table_name)
