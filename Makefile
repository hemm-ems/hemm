.PHONY: test test-container test-pi test-slow ci ci-full lint format build clean check-clock branding-audit

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

## CI minimum: lint + type check + clock audit + unit tests
ci: lint typecheck check-clock test

## Time-warp audit: forbid direct `datetime.now`/`time.monotonic`/`dt_util.utcnow`
## in domain code. Whitelist: hemm/time/, CLI entry points.
check-clock:
	uv run python tools/check_clock.py \
		--root src/hemm_core \
		--allow src/hemm_core/time \
		--allow src/hemm_core/cli.py \
		--allow src/hemm_core/__main__.py

## Branding audit: intentionally allowed to fail until the Phase 3 rename lands.
branding-audit:
	python3 ../tools/branding_audit.py

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
