# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_PYTHON_PREFERENCE=system \
    HTTP_PROXY="" \
    HTTPS_PROXY="" \
    http_proxy="" \
    https_proxy="" \
    NO_PROXY="*" \
    no_proxy="*"

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./

# Create virtual environment explicitly and sync dependencies
RUN uv venv /app/.venv && \
    uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}" \
    DJANGO_SETTINGS_MODULE="config.settings"

# Pre-bundle the ip2region offline database so the IP geolocation feature
# works out of the box without requiring operators to mount or download the
# xdb file at runtime. The build aborts if the download fails or the file is
# empty so we never ship a broken image. Local development can still override
# IP2REGION_XDB_PATH via .env.
ARG IP2REGION_XDB_URL="https://github.com/lionsoul2014/ip2region/raw/refs/heads/master/data/ip2region_v4.xdb"
RUN mkdir -p /app/data \
    && python -c "import urllib.request; urllib.request.urlretrieve('${IP2REGION_XDB_URL}', '/app/data/ip2region_v4.xdb')" \
    && test -s /app/data/ip2region_v4.xdb

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
COPY --from=builder /app/staticfiles /app/staticfiles
COPY --from=builder /app/templates /app/templates
COPY --from=builder /app/pyproject.toml /app/pyproject.toml
COPY --from=builder /app/uv.lock /app/uv.lock
COPY --from=builder /app/.env.example /app/.env.example
COPY --from=builder /app/shenbianyun /app/shenbianyun
COPY --from=builder /app/talent_reach /app/talent_reach
# Carry the pre-downloaded ip2region xdb file into the runtime image and
# point the application at it. Operators do not need to set IP2REGION_XDB_PATH
# manually; .env may still override this for local development.
COPY --from=builder /app/data /app/data
ENV IP2REGION_XDB_PATH="/app/data/ip2region_v4.xdb"

COPY docker-endpoint.sh /app/docker-endpoint.sh

RUN chmod +x /app/docker-endpoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker-endpoint.sh"]
