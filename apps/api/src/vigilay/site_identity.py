"""Identidad y credencial estable del agente local de una sede."""

import json
import os
import secrets
from pathlib import Path

from cryptography.exceptions import InvalidTag
from sqlalchemy import select

from vigilay.db import system_session
from vigilay.models import RecorderConnection, Site, Tenant
from vigilay.security import decrypt_credentials, encrypt_credentials


def load_scope():
    path = Path(os.getenv("VIGILAY_LOCAL_IDENTITY_PATH", ".local/vigilay-local.json"))
    try:
        identity = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError("Configura primero la empresa y sede en Vigilay Local") from exc
    tenant_id, site_id = identity.get("tenant_id"), identity.get("site_id")
    with system_session() as db:
        tenant, site = db.get(Tenant, tenant_id), db.get(Site, site_id)
        if tenant is None or tenant.status != "ACTIVE":
            raise RuntimeError("La empresa de Vigilay Local no existe o está inactiva")
        if site is None or site.tenant_id != tenant.id:
            raise RuntimeError("La sede de Vigilay Local no pertenece a la empresa")
    return tenant_id, site_id


def load_or_create_gateway_token(tenant_id, site_id):
    with system_session() as db:
        row = db.scalar(select(RecorderConnection).where(RecorderConnection.site_id == site_id))
        if row is None:
            row = RecorderConnection(tenant_id=tenant_id, site_id=site_id)
            db.add(row)
            db.flush()
        elif row.tenant_id != tenant_id:
            raise RuntimeError("La conexión registrada pertenece a otra empresa")
        if row.gateway_token_encrypted:
            try:
                return decrypt_credentials(row.gateway_token_encrypted, tenant_id, site_id)[
                    "gateway_token"
                ]
            except (InvalidTag, KeyError, ValueError) as exc:
                raise RuntimeError("No se pudo descifrar la credencial de esta sede") from exc
        token = secrets.token_urlsafe(48)
        row.gateway_token_encrypted = encrypt_credentials(
            {"gateway_token": token}, tenant_id, site_id
        )
        db.commit()
        return token
