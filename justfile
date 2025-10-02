run:
    @uv run manage.py runserver_plus

sh:
    @uv run manage.py shell_plus

test:
    uv run coverage run manage.py test --parallel
    uv run coverage combine
    uv run coverage report
