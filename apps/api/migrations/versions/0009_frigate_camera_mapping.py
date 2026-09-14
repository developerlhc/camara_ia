"""Map each Vigilay camera to its Frigate camera name.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cameras", sa.Column("frigate_camera_name", sa.String(length=80), nullable=True)
    )
    op.create_unique_constraint(
        "uq_camera_site_frigate_name", "cameras", ["site_id", "frigate_camera_name"]
    )


def downgrade():
    op.drop_constraint("uq_camera_site_frigate_name", "cameras", type_="unique")
    op.drop_column("cameras", "frigate_camera_name")
