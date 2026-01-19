# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_PYTHON_PREFERENCE=system

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./

# Create virtual environment explicitly and sync dependencies
RUN uv venv /app/.venv && \
    uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}" \
    DJANGO_SETTINGS_MODULE="config.settings"

COPY . .

RUN cp .env.example .env \
    && python manage.py collectstatic --noinput \
    && rm .env


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:${PATH}" \
    DJANGO_SETTINGS_MODULE="config.settings"

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv

COPY --from=builder /app/manage.py /app/manage.py
COPY --from=builder /app/config /app/config
COPY --from=builder /app/accounts /app/accounts
COPY --from=builder /app/chdb /app/chdb
COPY --from=builder /app/common /app/common
COPY --from=builder /app/contributions /app/contributions
COPY --from=builder /app/homepage /app/homepage
COPY --from=builder /app/messages /app/messages
COPY --from=builder /app/points /app/points
COPY --from=builder /app/shop /app/shop
COPY --from=builder /app/static /app/static
COPY --from=builder /app/staticfiles /app/staticfiles
COPY --from=builder /app/templates /app/templates
COPY --from=builder /app/pyproject.toml /app/pyproject.toml
COPY --from=builder /app/uv.lock /app/uv.lock
COPY --from=builder /app/.env.example /app/.env.example

COPY docker-endpoint.sh /app/docker-endpoint.sh

RUN chmod +x /app/docker-endpoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker-endpoint.sh"]
