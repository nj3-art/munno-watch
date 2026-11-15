"""add administrator audit logs

Revision ID: 3f64a6c40e62
Revises: 2b87a3a57a12
Create Date: 2026-11-15 14:48:19.741309

"""
from alembic import context, op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3f64a6c40e62'
down_revision = '2b87a3a57a12'
branch_labels = None
depends_on = None


def upgrade():
    if context.is_offline_mode() or "audit_logs" not in set(
        sa.inspect(op.get_bind()).get_table_names()
    ):
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("actor_user_id", sa.Integer(), nullable=True),
            sa.Column("action", sa.String(length=64), nullable=False),
            sa.Column("entity_type", sa.String(length=64), nullable=False),
            sa.Column("entity_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.String(length=32), nullable=False),
            sa.ForeignKeyConstraint(
                ["actor_user_id"], ["users.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade():
    if context.is_offline_mode() or "audit_logs" in set(
        sa.inspect(op.get_bind()).get_table_names()
    ):
        op.drop_table("audit_logs")
