"""camera brand and model

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cameras",
        sa.Column("brand", sa.String(length=32), nullable=False, server_default="GENERIC"),
    )
    op.add_column(
        "cameras",
        sa.Column("model", sa.String(length=120), nullable=False, server_default=""),
    )


def downgrade():
    op.drop_column("cameras", "model")
    op.drop_column("cameras", "brand")
