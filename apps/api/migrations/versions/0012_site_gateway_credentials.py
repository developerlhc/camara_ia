"""Store a distinct encrypted Frigate gateway credential per site.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "frigate_connections",
        sa.Column("gateway_token_encrypted", sa.LargeBinary(), nullable=True),
    )


def downgrade():
    op.drop_column("frigate_connections", "gateway_token_encrypted")
