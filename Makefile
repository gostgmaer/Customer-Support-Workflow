.PHONY: install dev test lint typecheck evaluate docker-up docker-down migrate seed seed-storefront

install:
	pip install -e ".[dev]"

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

seed:
	python scripts/seed/seed_data.py

seed-storefront:
	STOREFRONT_BASE_URL=$${STOREFRONT_BASE_URL:-http://localhost:8100} python scripts/seed/seed_storefront_integration.py

test:
	pytest -q

lint:
	ruff check .

typecheck:
	mypy app

evaluate:
	python tests/evaluation/run_evaluation.py

docker-up:
	docker compose up --build

docker-down:
	docker compose down -v

migrate:
	alembic upgrade head
