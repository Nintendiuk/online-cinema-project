# Online Cinema — backend

FastAPI backend for an online cinema: movie catalog, cart, orders, Stripe payments.

## Stack

Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · asyncpg · Alembic · PostgreSQL 16 ·
Pydantic v2 · Redis · Celery + celery-beat · MinIO · Stripe · Poetry · Docker Compose.

## Local setup

```powershell
Copy-Item .env.sample .env
poetry install
docker compose up --build
```

The API is served at http://localhost:8000, MailHog UI at http://localhost:8025,
MinIO console at http://localhost:9001.

## Checks

```powershell
poetry run ruff check .
poetry run black --check .
poetry run mypy --strict src/
poetry run pytest
```

Integration tests require a reachable PostgreSQL instance (`docker compose up db`).
To skip them: `poetry run pytest -m "not integration"`.

Engineering rules live in `CLAUDE.md`; architecture and phase plans in `docs/`.
