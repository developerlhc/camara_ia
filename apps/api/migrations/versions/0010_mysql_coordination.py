"""Move rate limits, heartbeats and simulator state to MySQL.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "rate_limit_buckets",
        sa.Column("bucket_key", sa.String(length=64), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("bucket_key"),
    )
    op.create_index(
        op.f("ix_rate_limit_buckets_expires_at"),
        "rate_limit_buckets",
        ["expires_at"],
        unique=False,
    )
    op.create_table(
        "service_heartbeats",
        sa.Column("service_name", sa.String(length=64), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("service_name"),
    )
    op.create_index(
        op.f("ix_service_heartbeats_last_seen_at"),
        "service_heartbeats",
        ["last_seen_at"],
        unique=False,
    )
    op.create_table(
        "simulator_states",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("camera_id", sa.String(length=36), nullable=False),
        sa.Column("motion_sensitivity", sa.Integer(), nullable=False),
        sa.Column("offline", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["camera_id", "tenant_id"],
            ["cameras.id", "cameras.tenant_id"],
            name="fk_simulator_state_camera_tenant",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("camera_id"),
    )


def downgrade():
    op.drop_table("simulator_states")
    op.drop_index(op.f("ix_service_heartbeats_last_seen_at"), table_name="service_heartbeats")
    op.drop_table("service_heartbeats")
    op.drop_index(op.f("ix_rate_limit_buckets_expires_at"), table_name="rate_limit_buckets")
    op.drop_table("rate_limit_buckets")
