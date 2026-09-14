"""camera video preferences

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cameras",
        sa.Column("target_fps", sa.Integer(), nullable=False, server_default="10"),
    )
    op.add_column(
        "cameras",
        sa.Column("grayscale", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("cameras", "grayscale")
    op.drop_column("cameras", "target_fps")
