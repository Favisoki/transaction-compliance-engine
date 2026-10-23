.PHONY: install test lint format up down logs ps api worker beat services-up services-down services-status

install:
	python3 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/pip install -r requirements-dev.txt

test:
	.venv/bin/pytest

lint:
	.venv/bin/ruff check .

format:
	.venv/bin/ruff format .

api:
	.venv/bin/uvicorn app.main:app --reload

worker:
	.venv/bin/celery -A app.core.celery_app worker --loglevel=INFO

beat:
	.venv/bin/celery -A app.core.celery_app beat --loglevel=INFO

services-up:
	./scripts/local_services.sh start

services-down:
	./scripts/local_services.sh stop

services-status:
	./scripts/local_services.sh status

up:
	docker compose up --build

down:
	docker compose down -v

logs:
	docker compose logs -f api worker beat

ps:
	docker compose ps
