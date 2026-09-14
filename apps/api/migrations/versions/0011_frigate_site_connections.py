"""Add one private Frigate gateway connection per site.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "frigate_connections",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("endpoint_url", sa.String(length=2048), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["site_id", "tenant_id"],
            ["sites.id", "sites.tenant_id"],
            name="fk_frigate_connection_site_tenant",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", name="uq_frigate_connection_site"),
    )
    op.create_index(
        op.f("ix_frigate_connections_tenant_id"),
        "frigate_connections",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_frigate_connections_site_id"),
        "frigate_connections",
        ["site_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_frigate_connections_last_seen_at"),
        "frigate_connections",
        ["last_seen_at"],
        unique=False,
    )


def downgrade():
    op.drop_table("frigate_connections")
