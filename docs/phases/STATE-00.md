STATE-00

Створені модулі:
  src/core/config.py      — Settings(postgres_user, postgres_password, postgres_db,
                            postgres_host, postgres_port, secret_key_access,
                            secret_key_refresh, jwt_algorithm, access_token_ttl_minutes,
                            refresh_token_ttl_days, activation_token_ttl_hours,
                            password_reset_ttl_minutes, email_host, email_port,
                            email_user, email_password, email_from, email_use_tls,
                            redis_url, celery_broker_url, celery_result_backend,
                            s3_endpoint, s3_access_key, s3_secret_key, s3_bucket_name,
                            stripe_secret_key, stripe_webhook_secret,
                            stripe_success_url, stripe_cancel_url, environment,
                            docs_enabled);
                            properties: database_url -> str, sync_database_url -> str,
                            is_production -> bool; get_settings() -> Settings (lru_cache)
  src/core/exceptions.py  — AppError(message: str | None, details: dict[str, Any] | None),
                            ValidationError, NotFoundError, ConflictError,
                            AuthenticationError, PermissionDeniedError,
                            TokenExpiredError, ExternalServiceError
                            (кожен має класовий атрибут default_message)
  src/core/celery_app.py  — celery_app: Celery
  src/db/base.py          — Base, NAMING_CONVENTION, IntPKMixin, TimestampMixin,
                            TokenMixin.is_expired(now: datetime | None = None) -> bool
  src/db/session.py       — engine: AsyncEngine,
                            async_session_factory: async_sessionmaker[AsyncSession],
                            get_session() -> AsyncGenerator[AsyncSession, None]
  src/api/v1/router.py    — api_router: APIRouter (порожній агрегатор, префікс /api/v1)
  src/main.py             — ERROR_STATUS_CODES: dict[type[AppError], int],
                            status_code_for(error: AppError) -> int,
                            app_error_handler(request, exc) -> JSONResponse,
                            create_app() -> FastAPI
  tests/conftest.py       — фікстури: engine (session), _schema (session, autouse),
                            db_session, app, async_client
  alembic/env.py          — async-міграції, target_metadata = Base.metadata,
                            compare_type=True, URL із Settings
  docker/, docker-compose.yml, alembic.ini, .env.sample, pyproject.toml, .gitignore,
  .dockerignore, README.md

Прийняті рішення, що впливають на наступні фази:
  - Мапінг доменних помилок на HTTP існує лише в src/main.py:
    ValidationError 422, NotFoundError 404, ConflictError 409, AuthenticationError 401,
    PermissionDeniedError 403, TokenExpiredError 400, ExternalServiceError 502,
    AppError 500. Тіло відповіді: {"detail": message, "details": details}.
  - Settings — плоский клас; імена полів = ключі .env.sample один в один,
    відповідність закріплена тестом. Нове поле без запису в .env.sample ламає тест.
  - database_url / sync_database_url — @property, не поля: інакше вони потрапили б у
    model_fields і зламали цей тест.
  - Ізоляція тестів: NullPool + connection.begin() + AsyncSession(
    join_transaction_mode="create_savepoint"), rollback після кожного тесту.
    Схема створюється один раз на сесію.
  - Тести ходять у справжній PostgreSQL (не sqlite): db_session, а через нього
    async_client, вимагають запущеного db. Без БД доступний лише `pytest -m unit`.
  - Міграції в контейнерах виконуються тільки там, де RUN_MIGRATIONS=1 (сервіс web);
    entrypoint робить exec "$@", команда за замовчуванням — у CMD Dockerfile.
  - Celery-застосунок — src/core/celery_app.py:celery_app; таски наступних фаз
    реєструються там.
  - Роутери фаз підключаються до api_router у src/api/v1/router.py; префікс /api/v1
    задається один раз у create_app().
  - Гроші: Decimal + NUMERIC(10,2); час: DateTime(timezone=True), UTC (datetime.UTC).

Відомий технічний борг:
  - src.core.exceptions.ValidationError тінює pydantic.ValidationError — у тестах і
    модулях, де потрібні обидва, імпортувати модулем або з псевдонімом.
  - CORS відкритий (allow_origins=["*"]) — звузити перед продакшеном.
  - celery-worker і celery-beat без healthcheck (у beat немає ping-інтерфейсу):
    гейт «7 сервісів» читається як 5 healthy + 2 running.
  - sync_database_url використовує драйвер psycopg2, якого немає в залежностях:
    придатний лише для alembic offline-режиму.
  - aiosqlite лишається в dev-залежностях невикористаним (запас на швидкі unit-прогони).
  - Порт 5432 опублікований у compose для локальних прогонів pytest.
