---
name: run-tests
description: Run fast unit tests for the hemm core library
command: make test
---

Runs `make test` which executes `uv run pytest` with the default marker filter (excludes container, pi, slow tests). Use this after every code change.
