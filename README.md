# OpenShare

OpenShare is a platform that rewards open‑source contributors. It provides point issuance, tagging, redemption, user profiles and search, messaging, and optional analytics so communities can compensate contributors transparently.

## Features
- Multi‑provider OAuth: GitHub, GitLab, Google, Bitbucket, and more via `social-auth-app-django`.
- Profiles & search: searchable public pages by username, company, location, and minimum points with caching.
- Points system: tagged point pools (withdrawable/rechargeable), issuance/consumption, expiry, withdrawals, and transaction history (`points` app).
- Shop & redemption: items can restrict allowed tags, support stock, shipping addresses, and status tracking (`shop` app).
- Messaging & feedback: site messages/flash notices to guide users.
- Optional infrastructure: Redis caching and ClickHouse analytics; Whitenoise serves static files.

## Quickstart
Requirements: Python 3.12+, `uv`, `just`; optional Redis and ClickHouse. SQLite is the default DB; PostgreSQL recommended for production.

```bash
# 1) Tooling
pip install uv
brew install just   # or install via your distro

# 2) Install deps
uv sync

# 3) Environment variables
cp .env.example .env
# fill SECRET_KEY, social auth keys, Mailgun, S3/Redis/ClickHouse, etc.

# 4) Migrate DB & create admin
uv run manage.py migrate
uv run manage.py createsuperuser

# 5) Run (dev)
just run           # runserver_plus at http://127.0.0.1:8000/
just worker        # run background DB worker in another terminal
```

Handy commands:
- `just fmt`: Ruff lint + format + djlint (run before committing).
- `just test`: parallel Django tests with coverage.
- `uv run manage.py grant_points <username> <amount> --tags=tag1,tag2`: issue points.
- `uv run manage.py shell_plus` or `just sh`: interactive shell.

## Configuration Notes
- Copy `.env.example` → `.env`; in production set `DEBUG=False`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`.
- Email: set `MAILGUN_API_KEY` and `MAILGUN_SENDER_DOMAIN`; when empty, emails print to console for local dev.
- Object storage: configure all `AWS_*` values for S3/compatible storage; otherwise local filesystem is used.
- Social auth: create provider apps and supply key/secret; scopes are comma-separated.
- Caching/analytics: `REDIS_URL` enables cache middleware; ClickHouse settings enable `chdb` analytics features.

## Directory Map
- `config/`: Django settings, URLs, ASGI/WSGI entrypoints.
- `accounts/`: custom user, profiles, shipping addresses, social connections.
- `homepage/`: landing page and user search.
- `points/`: point pools, transactions, services, and management commands.
- `shop/`: shop items, redemptions, shipping flow.
- `messages/`: site messages/notifications.
- `chdb/`: ClickHouse integrations (optional).
- `templates/`, `static/`: frontend templates and static assets.
- `justfile`: common dev/CI commands.

## Deployment Tips
- Ensure `just fmt` and `just test` pass before deploying; container flows use `just docker-build` / `just docker-test` with `.env.example`.
- Production requires a persistent DB and object storage; run `collectstatic` and serve via Whitenoise or a CDN.
- Behind proxies/load balancers, keep forwarded headers (`USE_X_FORWARDED_HOST/PORT`) — already enabled in settings.

## Support & Contributions
Issues and PRs are welcome. See [contribute.md](contribute.md) for contribution flow and [development.md](development.md) for local environment details.
