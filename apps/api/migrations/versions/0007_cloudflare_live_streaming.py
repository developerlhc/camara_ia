"""cloudflare on-demand live streaming

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "camera_stream_providers",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("camera_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_live_input_uid", sa.String(length=64), nullable=False),
        sa.Column("publish_url_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("playback_url", sa.String(length=2048), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["camera_id", "tenant_id"],
            ["cameras.id", "cameras.tenant_id"],
            name="fk_stream_provider_camera_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("camera_id"),
        sa.UniqueConstraint("provider_live_input_uid"),
    )
    op.create_index(
        op.f("ix_camera_stream_providers_camera_id"),
        "camera_stream_providers",
        ["camera_id"],
    )
    op.create_index(
        op.f("ix_camera_stream_providers_tenant_id"),
        "camera_stream_providers",
        ["tenant_id"],
    )
    op.create_table(
        "camera_stream_sessions",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("camera_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("viewer_key_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=False),
        sa.Column("stopped_at", sa.DateTime(), nullable=True),
        sa.Column("stop_reason", sa.String(length=64), nullable=True),
        sa.Column("sanitized_error", sa.String(length=300), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('starting','live','stopping','stopped','error')",
            name="ck_stream_session_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["camera_id", "tenant_id"],
            ["cameras.id", "cameras.tenant_id"],
            name="fk_stream_session_camera_tenant",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("viewer_key_hash"),
    )
    op.create_index(
        op.f("ix_camera_stream_sessions_camera_id"),
        "camera_stream_sessions",
        ["camera_id"],
    )
    op.create_index(
        "ix_stream_session_camera_status",
        "camera_stream_sessions",
        ["camera_id", "status"],
    )
    op.create_index(
        op.f("ix_camera_stream_sessions_last_heartbeat_at"),
        "camera_stream_sessions",
        ["last_heartbeat_at"],
    )
    op.create_index(
        op.f("ix_camera_stream_sessions_tenant_id"),
        "camera_stream_sessions",
        ["tenant_id"],
    )
    op.create_index(
        op.f("ix_camera_stream_sessions_user_id"),
        "camera_stream_sessions",
        ["user_id"],
    )


def downgrade():
    op.drop_table("camera_stream_sessions")
    op.drop_table("camera_stream_providers")
