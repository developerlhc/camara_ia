"""Initial fixed RBAC policy.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

POLICY = {
    "SUPER_ADMIN": [
        "tenants.manage",
        "sites.manage",
        "users.manage",
        "cameras.read",
        "cameras.manage",
        "cameras.configure",
        "audit.read",
        "system.read",
    ],
    "CLIENT_ADMIN": [
        "sites.manage",
        "users.manage",
        "cameras.read",
        "cameras.manage",
        "cameras.configure",
        "audit.read",
    ],
    "OPERATOR": ["cameras.read", "cameras.configure"],
    "VIEWER": ["cameras.read"],
}


def upgrade():
    roles = sa.table(
        "roles",
        sa.column("name", sa.String),
        sa.column("scope", sa.String),
        sa.column("description", sa.String),
    )
    permissions = sa.table(
        "permissions", sa.column("key", sa.String), sa.column("description", sa.String)
    )
    grants = sa.table(
        "role_permissions",
        sa.column("role_name", sa.String),
        sa.column("permission_key", sa.String),
    )
    op.bulk_insert(
        roles,
        [
            {
                "name": name,
                "scope": "GLOBAL" if name == "SUPER_ADMIN" else "TENANT",
                "description": description,
            }
            for name, description in [
                ("SUPER_ADMIN", "Administración global"),
                ("CLIENT_ADMIN", "Administración del cliente"),
                ("OPERATOR", "Operación de cámaras asignadas"),
                ("VIEWER", "Consulta de cámaras asignadas"),
            ]
        ],
    )
    op.bulk_insert(permissions, [{"key": key, "description": key} for key in POLICY["SUPER_ADMIN"]])
    op.bulk_insert(
        grants,
        [
            {"role_name": role, "permission_key": key}
            for role, keys in POLICY.items()
            for key in keys
        ],
    )


def downgrade():
    # Role grants are referenced by real users; removing this policy requires an explicit migration.
    raise RuntimeError(
        "No se revierte RBAC automáticamente; crea una migración de política explícita"
    )
