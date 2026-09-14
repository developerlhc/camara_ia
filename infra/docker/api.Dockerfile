FROM python:3.13-slim AS builder
WORKDIR /src
COPY pyproject.toml ./
COPY apps/api/src apps/api/src
COPY services/camera-adapters/src services/camera-adapters/src
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.13-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && useradd --create-home --uid 10001 vigilay
COPY alembic.ini ./
COPY apps/api/migrations apps/api/migrations
USER vigilay
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=3)"
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn vigilay.main:create_app --factory --host 0.0.0.0 --port 8000 --no-access-log --no-proxy-headers"]
