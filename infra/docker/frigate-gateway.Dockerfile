FROM python:3.13-slim AS builder
WORKDIR /src
COPY pyproject.toml ./
COPY apps/api/src apps/api/src
COPY services/camera-adapters/src services/camera-adapters/src
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

FROM cloudflare/cloudflared:2026.9.1 AS cloudflared

FROM python:3.13-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && useradd --create-home --uid 10001 vigilay
COPY --from=cloudflared /usr/local/bin/cloudflared /usr/local/bin/cloudflared
USER vigilay
CMD ["vigilay-frigate-gateway"]
