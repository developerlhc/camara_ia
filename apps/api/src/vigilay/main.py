import json
import logging
import time
from datetime import timedelta
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from vigilay import auth, frigate_routes, live_routes, realtime, routes
from vigilay.config import settings
from vigilay.db import engine, system_session
from vigilay.models import ServiceHeartbeat, utcnow

logger = logging.getLogger("vigilay")


def create_app():
    config = settings()
    if config.app_env == "production" and len(config.internal_proxy_secret) < 32:
        raise RuntimeError("La API en producción requiere INTERNAL_PROXY_SECRET aleatorio")
    app = FastAPI(
        title="Vigilay",
        version="0.2.1",
        docs_url="/api/docs" if config.app_env != "production" else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[config.web_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["content-type", "x-csrf-token"],
    )

    @app.middleware("http")
    async def request_security(request: Request, call_next):
        request_id = str(uuid4())
        started = time.monotonic()
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and request.headers.get("origin") != config.web_origin
        ):
            return JSONResponse({"detail": "Origen de solicitud no permitido"}, status_code=403)
        response = await call_next(request)
        response.headers.update(
            {
                "X-Request-ID": request_id,
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
                "X-Frame-Options": "DENY",
                "Server-Timing": f"api;dur={(time.monotonic() - started) * 1000:.1f}",
            }
        )
        logger.info(
            json.dumps(
                {
                    "service": "api",
                    "request_id": request_id,
                    "method": request.method,
                    "status": response.status_code,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                }
            )
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Pydantic's default error includes input values, potentially containing credentials.
        return JSONResponse(
            {
                "detail": "Datos inválidos",
                "fields": [
                    {"loc": list(error["loc"]), "type": error["type"]} for error in exc.errors()
                ],
            },
            status_code=422,
        )

    @app.exception_handler(IntegrityError)
    async def conflict(request, exc):
        return JSONResponse({"detail": "Datos duplicados o referencia inválida"}, status_code=409)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        logger.error(json.dumps({"service": "api", "event_type": "DATABASE_UNAVAILABLE"}))
        return JSONResponse(
            {"detail": "Base de datos temporalmente no disponible"}, status_code=503
        )

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"service": "Vigilay API", "status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz():
        try:
            with engine().connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {"status": "ok"}

    @app.get("/api/v1/system/health")
    def system_health(actor=Depends(auth.require("system.read"))):
        ready = readyz()
        if isinstance(ready, JSONResponse):
            return ready
        cutoff = utcnow() - timedelta(seconds=30)
        with system_session() as db:
            worker = db.get(ServiceHeartbeat, "worker")
            media = db.get(ServiceHeartbeat, "stream-agent")
        return {
            "api": "ok",
            "mysql": "ok",
            "coordination": "mysql",
            "worker": "ok" if worker and worker.last_seen_at >= cutoff else "offline",
            "media": "ok" if media and media.last_seen_at >= cutoff else "offline",
        }

    app.include_router(auth.router)
    app.include_router(routes.router)
    app.include_router(live_routes.router)
    app.include_router(frigate_routes.router)
    app.include_router(realtime.router)
    return app
