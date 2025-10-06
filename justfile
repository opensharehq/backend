run:
    @uv run manage.py runserver_plus

sh:
    @uv run manage.py shell_plus

worker:
    @uv run manage.py db_worker

manage *args:
    @uv run manage.py {{args}}

fmt:
    @uvx ruff check   # Lint all files in the current directory.
    @uvx ruff format  # Format all files in the current directory.
    @uv run -m pre_commit run  djlint-django --all-files


db_update:
    @uv run manage.py makemigrations
    @uv run manage.py migrate

test:
    @uv run coverage run manage.py test --parallel --keepdb --timing --durations 10
    @uv run coverage report

docker-build IMAGE='fullsite':
    docker build --tag {{IMAGE}} .

docker-test IMAGE='fullsite': docker-build
    docker run --rm --env-file .env.example {{IMAGE}} python manage.py test --parallel
