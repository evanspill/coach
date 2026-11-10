.PHONY: install check lint format typecheck test simulate scenarios fixtures

install:  ## dev install
	pip install -e ".[dev]"

check: lint typecheck test simulate  ## everything CI runs

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

typecheck:
	mypy src/coach

test:
	pytest --cov=coach --cov-report=term-missing:skip-covered --cov-fail-under=80

simulate:
	COACH_MOCK=1 python -m coach validate config
	COACH_MOCK=1 python -m coach simulate --days 120 --from 2026-11-16 --quiet
	COACH_MOCK=1 python -m coach simulate --days 120 --from 2026-11-16 --quiet --config active --no-scenarios

scenarios:
	COACH_MOCK=1 python -m coach scenarios

fixtures:  ## regenerate the demo athlete mock data
	python scripts/generate_fixtures.py
