# Contributing to HEMM

## Development Setup

1. Clone both repos under one parent directory
2. Create a virtual environment: `uv venv`
3. Install in dev mode: `uv pip install -e ".[dev]"`
4. Install pre-commit hooks: `uv run pre-commit install`

## Workflow

1. Create a branch from `main`
2. Make changes
3. Run `make ci` to verify
4. Open a PR with Conventional Commit message

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation only
- `test:` adding/updating tests
- `chore:` tooling, CI, dependencies
- `refactor:` code change that neither fixes a bug nor adds a feature

## Code Style

- Ruff for linting and formatting (configured in `pyproject.toml`)
- mypy strict mode for type checking
- All tests require a marker (`unit`, `container`, `pi`, `slow`)
