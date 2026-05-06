.PHONY: test test-container test-pi test-slow ci ci-full lint format build clean

## Default: fast unit tests only
test:
	uv run pytest

## Container-based integration tests (Docker required)
test-container:
	uv run pytest -m container

## Pi hardware tests (manual / self-hosted runner)
test-pi:
	uv run pytest -m pi

## Long-running simulation tests
test-slow:
	uv run pytest -m slow

## CI minimum: lint + type check + unit tests
ci: lint typecheck test

## CI full: ci + container tests
ci-full: ci test-container

## Lint and format check
lint:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

## Auto-format
format:
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

## Type checking (strict)
typecheck:
	uv run mypy

## Build wheel
build:
	uv build

## Clean build artifacts
clean:
	rm -rf dist/ build/ *.egg-info src/*.egg-info .mypy_cache .pytest_cache .coverage htmlcov/
