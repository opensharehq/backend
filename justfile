run:
    @uv run manage.py runserver_plus

run_plus:
    @uv run manage.py runserver_plus

sh:
    @uv run manage.py shell_plus

worker:
    @uv run manage.py db_worker

manage *args:
    @uv run manage.py {{args}}

fmt:
    @uvx ruff check  --fix   # Lint all files in the current directory.
    @uvx ruff format # Format all files in the current directory.
    @uv run -m pre_commit run  djlint-django --all-files


migrate:
    @uv run manage.py makemigrations
    @uv run manage.py migrate

test:
    @uv run python -m playwright install chromium
    @uv run python -m coverage erase
    @DJANGO_LOG_LEVEL=ERROR uv run python -m coverage run --concurrency=multiprocessing --parallel-mode manage.py test --exclude-tag=e2e --parallel --timing --durations 10
    @DJANGO_LOG_LEVEL=ERROR uv run python -m coverage run --parallel-mode manage.py test config.tests.test_asgi config.tests.test_wsgi config.tests.test_coverage_gate --timing
    @DJANGO_LOG_LEVEL=ERROR uv run python -m coverage run --parallel-mode manage.py test config.tests.test_frontoffice_e2e config.tests.test_backoffice_e2e --timing --durations 10
    @uv run python -m coverage combine
    @uv run python -m coverage json
    @uv run python -m coverage report
    @uv run python scripts/check_coverage.py coverage.json --line-threshold 95 --branch-threshold 85
    @uv run python -m coverage report --skip-covered --skip-empty

test-security:
    @DJANGO_LOG_LEVEL=ERROR uv run manage.py test config.tests.test_security_owasp --timing

load-test *args:
    @uv run python scripts/load_test.py {{args}}

mutmut:
    @uv run --python 3.12 --with mutmut --with pytest --with pytest-django mutmut run

mutmut-results:
    @uv run --python 3.12 --with mutmut --with pytest --with pytest-django mutmut results

docker-build IMAGE='fullsite':
    docker build --network=host --tag {{IMAGE}} .

docker-test IMAGE='fullsite': docker-build
    docker run --network=host --rm --env-file .env.example {{IMAGE}} python manage.py test --parallel
