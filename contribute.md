# Contributing Guide

Thank you for considering a contribution to OpenShare! This document explains how to report issues, propose changes, and keep quality high.

## Ways to Contribute
- Report issues: describe the behavior, expected result, and reproduction steps; include OS, Python version, and DB type.
- Feature ideas: open an issue to discuss before building to avoid duplication or misalignment.
- Code changes: work from a fork or branch and submit a focused Pull Request.

## Workflow
1) Set up your environment per `development.md` and ensure the app runs locally.
2) Create a branch, e.g., `feature/<topic>`, `fix/<topic>`, or `chore/<topic>`.
3) Follow the repo conventions (below) and add/update tests and docs as needed.
4) Before committing, run `just fmt` and `just test` to keep linting and tests green.
5) Use Conventional Commits, e.g., `feat: add point tag validation`, `fix: handle empty search query`.
6) PR checklist:
   - Purpose/background of the change
   - Key modifications
   - Testing notes (commands or manual steps)
   - Database/migration impact
   - Screenshots for UI changes (if applicable)

## Coding & Style
- Python 3.12+, Ruff enforced; max line length 88; prefer double quotes; imports autosorted.
- Templates: Django templates with minimal logic; prefer custom tags/filters for reuse.
- Naming: snake_case for functions/variables, PascalCase for classes, lowercase_with_underscores for files.
- Security: never commit real secrets or `.env`; keep `DEBUG=False` in production.
- DB changes: generate migrations for model edits and include them in PRs; be cautious with existing fields.

## Testing Expectations
- New features and bug fixes should include tests covering core paths; place them in the app’s `tests/` package with `test_*.py`.
- Use `TestCase`/`APITestCase`; avoid global state; mock external services (email, S3, ClickHouse) when needed.
- Run `just test` before opening a PR; for smaller scopes, note any targeted test commands you ran.

## Code Review Tips
- Keep PRs small and focused; avoid bundling unrelated changes.
- Respond to reviewer comments and clarify intent when needed.
- If risks or missing tests remain, state them explicitly in the PR description.

## Code of Conduct
We expect respectful, constructive communication in issues and PRs. Let’s keep OpenShare welcoming and safe for all contributors.
