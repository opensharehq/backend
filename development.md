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
- App server: `just run` (runserver_plus on 127.0.0.1:8000). This starts only the web server.
- Background worker: `just worker` (django_tasks DB backend) in a separate terminal. Keep it running for queued tasks to execute.
- Shell: `just sh` or `uv run manage.py shell_plus`.
- Static files: served from `static/` in dev; run `python manage.py collectstatic` for production or S3 usage.

## Common Tasks
- Issue points: `uv run manage.py grant_points <username> <amount> --tags=tag1,tag2`.
- Search debugging: visit `/` or `/search?q=<keyword>` (results cached for 60s).
- Shop flow: create `ShopItem` in admin; set `allowed_tags` / `requires_shipping`; redemptions create `Redemption` + `PointTransaction` records.
- Logging: console-first today; see `TODOs.md` for planned structured logging improvements.

## Testing & Quality
- Full suite: `just test` (parallel with coverage).
- Security regression suite: `just test-security`.
- Start a local load-test target with `just run_plus`.
- Load testing against a running local server: `just load-test --base-url http://127.0.0.1:8000`.
- Mutation testing for curated high-signal modules: `just mutmut`.
- Targeted tests: `uv run manage.py test points.tests.test_services` (or any dotted path).
- Lint/format: `just fmt` (Ruff lint+format, djlint for templates). Run before committing.
- Test ownership and strategy details: `docs/testing-strategy.md`.

## Large point allocations

The frontend uploads allocations with more than 1,000 recipients through
`POST /api/v1/points/allocation-uploads`, followed by numbered `PUT` batches
of at most 1,000 recipients and a final `POST .../{id}/execute`. The total
recipient count does not determine the size of an individual request. Ordinary
users retain the existing recipient limit; platform administrators are uncapped.
Do not disable Django's request-body limit to accommodate large allocations.

Before deploying this flow, apply migrations with `uv run manage.py migrate`
and run a persistent database worker with
`uv run manage.py db_worker --no-reload` (or `just worker` during development).
The frontend status page `/points/allocations/{id}` polls small summaries; the
allocation detail endpoint paginates batched records using `registered_page`
and `pending_page` (20 rows per page).

If a submission stays `queued`, check the worker process and its logs: a
`READY` database task with no `started_at` or `worker_ids` has not been claimed.
Starting only `just run` leaves such tasks waiting indefinitely. Start the
worker to consume the existing task; do not create another allocation.
After all batches are uploaded, the execute request debits the initiator and
enqueues the task in one transaction. The wallet balance and debit history update
immediately when that request succeeds, including while the task is `queued`.
Recipient credits and pending grants remain uncommitted until the whole worker
transaction succeeds. In Docker, run an additional instance of the same image with
`IS_WORKER=1` and the same database configuration; the web instance alone does
not consume tasks.

For three containers in total, use two web replicas (`IS_WORKER=0`) and one
worker (`IS_WORKER=1`). If three web replicas are required, add a fourth
container for the worker. All must use the same migrated PostgreSQL database;
separate container-local SQLite files do not share uploaded batches or tasks.
Only web replicas belong behind the HTTP load balancer. Multiple workers may
consume the shared queue: transactional row locks allow only one worker to
claim a task. One allocation is processed by one worker, not split among workers.
Graceful shutdown still lets the current task finish when possible. If deployment
or a crash kills the worker, the restarted worker automatically recovers the
unfinished allocation; waiting for completion before every deployment is not
required for correctness.

Uploading alone does not deduct points. Submission UUIDs and immutable numbered
batches make identical retries safe. The execute request verifies the complete
upload and its total, locks spendable source lots, and records each prepaid lot
alongside its debit. A concurrent synchronous allocation or purchase can spend
only the remaining wallet balance. Insufficient funds reject execution with 409;
enqueue failure rolls back the debit too. Repeating an accepted request cannot
debit or enqueue it again.
Submitting or retrying an uploaded allocation rechecks the initiator's current
organization spending permission and recipient limit before debiting funds.

The worker reads at most 1,000 recipients per batch and distributes from the
allocation's prepaid lots, preserving tags and expiry dates. It does not debit
the initiator again or hold their spendable source locks for the entire run.
Individual recipient failures refund the undistributed portion at completion.
A fatal execution failure rolls back every recipient credit and pending grant,
then refunds the prepaid amount and marks the allocation failed atomically.
Refunds are ledger entries and restore the original point type, owner, tag and
expiry; expired points do not gain a new expiry date. Debits and refunds are
grouped separately in transaction history. Retrying a failed allocation requires
a new prepayment and balance check.

This release adds migration `0012_allocation_funding`. Stop all old worker
instances before deploying the new web and worker images: older workers use
the previous debit-on-completion protocol and must not consume prepaid tasks.
An interrupted old task can be recovered; it need not finish before stopping the
old worker. Apply migrations, deploy the new web image, then start workers from
the same new image. Previously queued tasks without a prepayment are prepaid
when the new worker claims them; insufficient balance fails these legacy tasks
without issuing a refund for points that were never charged.

### Worker restart and recovery

The project's `db_worker` command extends the database worker with recovery for
`execute_batched_allocation`. Existing Docker `IS_WORKER=1` and `just worker`
entry points use it automatically after deploying the new backend image. Keep
`points` before `django_tasks.backends.database` in `INSTALLED_APPS` so Django
selects this command. Worker autoreload defaults to off, including development.
Other task types retain their original execution behavior.

For allocations, the worker holds the database task row lock throughout the
transfer and commits task success in the **same transaction** as all recipient
credits, pending grants, unused-fund refunds and allocation completion.
An interrupted worker transaction rolls back these changes but retains the
earlier committed prepayment, uploaded batches and task. A crash awaiting recovery
is not a terminal failure: funds remain prepaid and cannot be spent elsewhere.
Recovery retries the original task ID from the first batch without another debit;
it is not a checkpoint resume from the last processed batch.
A crash after commit leaves the allocation and task completed, so no retry occurs.

Recovery runs at startup and every 10 seconds between tasks. A claimed task must
be at least 30 seconds old to cover the brief gap between claiming and acquiring
the execution lock. PostgreSQL `SKIP LOCKED` excludes tasks still running, even
when an allocation takes hours. Recovery also checks the allocation row lock to
avoid stealing a task from an older worker during rolling upgrades. After the
database releases a dead worker's locks, an available worker can reclaim it;
recovery can wait longer if all workers are busy. No manual re-enqueue is needed.

Ordinary execution failures remain failed with all recipient transfers rolled
back and prepaid funds refunded; resolve the cause and use the status page's
retry action. A stopped worker or a task waiting in the queue is not by itself
a reason to refund a task that can still be resumed.
Automatic crash recovery applies to background allocations only. The frontend
still sends at most 1,000 recipients to the synchronous `/allocations` endpoint;
larger submissions use `/allocation-uploads` and always require a worker. The
legacy synchronous endpoint itself does not automatically switch to background
execution based on recipient count.

Large runs still require enough database capacity and a transaction timeout
long enough for the full transfer. Preview calculation still loads the complete
recipient list in the browser; this change bounds upload, execution batches and
detail responses, and does not constitute a production throughput guarantee.
Scale tests cover 3,000,001 client upload records and a 3,000,000-recipient worker
loop. The worker scale test generates batches and replaces pending-row inserts;
separate integration tests exercise real writes, rollback and retry. Measure
full database throughput on deployment-sized infrastructure before choosing
worker concurrency or promising a completion time.

With `DATABASE_URL` pointing to a dedicated PostgreSQL test database, run
`uv run manage.py test points.tests.test_allocation_funding points.tests.test_allocation_worker points.tests.test_allocation_batches.AllocationWorkerConcurrencyTests`
to verify prepayment racing with synchronous allocations, spending the unreserved
balance during a running worker, real child-process `SIGKILL` during transfer or
refund and before/after commit, recovery after restart, exclusion of live workers,
and three simultaneous workers recovering or claiming a task only once.
These process/row-lock tests are skipped on SQLite;
the remaining worker recovery tests also run in the regular SQLite suite.

## Database & Migrations
- After model changes: `uv run manage.py makemigrations` and commit generated migrations.
- Pre-deploy check: `uv run manage.py migrate --check` to ensure no pending migrations.

## Docker (optional)
- Build image: `just docker-build IMAGE=fullsite`.
- Run tests in container: `just docker-test IMAGE=fullsite` (uses `.env.example`).
