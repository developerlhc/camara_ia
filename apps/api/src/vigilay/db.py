from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, with_loader_criteria

from vigilay.config import settings
from vigilay.models import Tenant, TenantScoped


class ScopedSession(Session):
    """Every domain unit of work must explicitly choose its authorization context."""


@event.listens_for(ScopedSession, "do_orm_execute")
def enforce_scope(state):
    if state.session.info.get("global_access"):
        return
    tenant_id = state.session.info.get("tenant_id")
    if not tenant_id:
        raise PermissionError("Contexto de cliente requerido")
    if not state.is_select or not state.is_orm_statement:
        raise PermissionError("Operaciones SQL masivas no permitidas en sesiones de cliente")
    state.statement = state.statement.options(
        with_loader_criteria(
            TenantScoped, lambda cls: cls.tenant_id == tenant_id, include_aliases=True
        ),
        with_loader_criteria(Tenant, lambda cls: cls.id == tenant_id, include_aliases=True),
    )


@event.listens_for(ScopedSession, "before_flush")
def enforce_writes(session, context, instances):
    if session.info.get("global_access"):
        return
    tenant_id = session.info.get("tenant_id")
    for row in session.new | session.dirty | session.deleted:
        if not isinstance(row, TenantScoped) or not tenant_id or row.tenant_id != tenant_id:
            raise PermissionError("Escritura fuera del cliente autorizado")


_engine = None


def engine():
    global _engine
    if _engine is None:
        config = settings()
        _engine = create_engine(
            config.database_url,
            pool_pre_ping=True,
            pool_recycle=300,
            pool_size=config.database_pool_size,
            max_overflow=config.database_max_overflow,
            pool_timeout=15,
            pool_use_lifo=True,
        )
    return _engine


@contextmanager
def system_session():
    # Restricted to authentication, CLI, migrations and trusted worker processes.
    with ScopedSession(engine(), info={"global_access": True}, expire_on_commit=False) as db:
        yield db


@contextmanager
def tenant_session(tenant_id, *, superadmin=False):
    with ScopedSession(
        engine(), info={"global_access": superadmin, "tenant_id": tenant_id}, expire_on_commit=False
    ) as db:
        yield db
