#!/bin/sh
set -o errexit
set -o pipefail
set -o nounset

# Create .env file from .env.example if it doesn't exist
if [ -f "/app/.env.example" ] && [ ! -f "/app/.env" ]; then
    cp /app/.env.example /app/.env
fi

# If arguments are provided, execute them directly
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

# Run database migrations
python manage.py migrate --noinput

# Check if running as a worker
if [ "${IS_WORKER:-0}" = "1" ]; then
    echo "Starting as worker (db_worker)..."
    exec python manage.py db_worker
else
    echo "Starting as web server on port ${PORT:-8000}..."
    exec gunicorn config.wsgi:application \
        --bind 0.0.0.0:"${PORT:-8000}" \
        --workers "${GUNICORN_WORKERS:-1}" \
        --timeout "${GUNICORN_TIMEOUT:-120}" \
        --access-logfile - \
        --error-logfile -
fi
