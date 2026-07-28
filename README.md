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
MinIO console at http://localhost:9001, PostgreSQL at localhost:5433.

## Checks

```powershell
poetry run ruff check .
poetry run black --check .
poetry run mypy --strict src/
poetry run pytest
```

The suite needs a reachable PostgreSQL instance (`docker compose up -d db`) because the
`db_session` fixture — and therefore `async_client` — connects for real. Unit tests run
without it: `poetry run pytest -m unit`.

`.env` describes the world as seen from your machine (`localhost`, host port 5433 for
PostgreSQL). `docker-compose.yml` overrides those hostnames with the in-network ones
(`db`, `redis`, `minio`, `mailhog`), so one `.env` serves both. If port 5433 is taken on
your machine, change the published port of the `db` service and `POSTGRES_PORT` together.

Engineering rules live in `CLAUDE.md`; architecture and phase plans in `docs/`.
