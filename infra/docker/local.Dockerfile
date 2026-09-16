FROM python:3.13-slim AS builder
WORKDIR /src
COPY pyproject.toml requirements-local.txt ./
COPY apps/api/src apps/api/src
COPY services/camera-adapters/src services/camera-adapters/src
RUN pip wheel --no-cache-dir --wheel-dir /wheels . -r requirements-local.txt

FROM python:3.13-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    CAMERA_STORAGE=mysql LOCAL_AI_ENABLED=false START_STREAM_AGENT_WITH_LOCAL=false \
    VIGILAY_LOCAL_CONTAINER=true VIGILAY_LOCAL_PREFER_RESTREAM=true \
    VIGILAY_LOCAL_DATA_DIR=/app/.local/data
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -r /wheels \
    && useradd --create-home --uid 10001 vigilay \
    && mkdir -p /app/.local/data && chown -R vigilay:vigilay /app/.local
COPY camara-ia.py camera_store.py local_runtime.py vigilay_local_server.py ./
COPY templates templates
USER vigilay
EXPOSE 5000
HEALTHCHECK --interval=20s --timeout=5s --start-period=60s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=3)"
CMD ["python", "vigilay_local_server.py"]
