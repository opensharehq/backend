# Development Guide

This guide is for developers who want to run or extend OpenShare locally.

## Prerequisites
- Python 3.12+ (pyenv recommended) and `uv` for dependency management.
- `just` command runner (e.g., `brew install just` on macOS).
- Optional services: Redis (cache), ClickHouse (analytics), PostgreSQL (production DB).

## Initial Setup
1) Clone the repo and `cd` into the project root.
2) Install deps: `uv sync` (use `uv sync --frozen` in CI for locked versions).
3) Copy env template: `cp .env.example .env`, then fill at least:
   - `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`
   - Mail: `MAILGUN_API_KEY`, `MAILGUN_SENDER_DOMAIN` (empty prints to console locally)
   - Storage: `AWS_*` for S3/compatible storage; if omitted, local filesystem is used
   - Cache: `REDIS_URL` (empty falls back to in‑memory cache)
   - Social auth: `SOCIAL_AUTH_*` keys/secrets; scopes are comma-separated
   - Analytics: `CLICKHOUSE_*` (optional)
4) Migrate DB: `uv run manage.py migrate`
5) Create admin: `uv run manage.py createsuperuser`

## Running Locally
- App server: `just run` (runserver_plus on 127.0.0.1:8000).
- Background worker: `just worker` (django_tasks DB backend) in a separate terminal.
- Shell: `just sh` or `uv run manage.py shell_plus`.
- Static files: served from `static/` in dev; run `python manage.py collectstatic` for production or S3 usage.

## Common Tasks
- Issue points: `uv run manage.py grant_points <username> <amount> --tags=tag1,tag2`.
- Search debugging: visit `/` or `/search?q=<keyword>` (results cached for 60s).
- Shop flow: create `ShopItem` in admin; set `allowed_tags` / `requires_shipping`; redemptions create `Redemption` + `PointTransaction` records.
- Logging: console-first today; see `TODOs.md` for planned structured logging improvements.

## Testing & Quality
- Full suite: `just test` (parallel with coverage).
- Targeted tests: `uv run manage.py test points.tests.test_services` (or any dotted path).
- Lint/format: `just fmt` (Ruff lint+format, djlint for templates). Run before committing.

## Database & Migrations
- After model changes: `uv run manage.py makemigrations` and commit generated migrations.
- Pre-deploy check: `uv run manage.py migrate --check` to ensure no pending migrations.

## Docker (optional)
- Build image: `just docker-build IMAGE=fullsite`.
- Run tests in container: `just docker-test IMAGE=fullsite` (uses `.env.example`).
