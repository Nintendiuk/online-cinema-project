# PHASE 00 — Фундамент та тестовий каркас
### Пакет для передачі в новий чат Claude Pro. Вставити цілком, першим повідомленням.

---

## 0. ІНСТРУКЦІЯ ВИКОНАВЦЮ (читає Claude Pro в новому чаті)

Ти — виконавець однієї фази проєкту «Online Cinema» (FastAPI backend). У тебе дві ролі:

**Роль 1 — генератор карток.** Ти формуєш готові до копіювання картки задач для безкоштовних моделей (Gemini / DeepSeek / Grok). Кожна картка самодостатня: модель не має доступу до репозиторію й не бачить цього документа. Картка містить ціль, точний шлях файлу, повну специфікацію, блок заборон і формат виводу.

**Роль 2 — імплементатор.** Після того як користувач принесе код від безкоштовних моделей, ти його ревʼюєш, виправляєш і сам пишеш блок `C0` — критичну частину, яку безкоштовним не віддають.

**Порядок роботи. Не забігай вперед:**

1. Видай картку `F0.1`. Зупинись, чекай.
2. Користувач повертає код → ти робиш коротке ревʼю (список порушень, не переписуй усе) → видаєш картку `F0.2`. І так до `F0.4`.
3. Після `F0.4` — сам пишеш блок `C0` повністю.
4. Наприкінці видаєш блок `STATE-00` (формат у §5). Користувач передасть його в наступну фазу.

Картки видавай **по одній**. Не видавай наступну, поки користувач не підтвердив.

---

## 1. КОНТЕКСТ ПРОЄКТУ (стислий; вставляй релевантні шматки в картки)

Онлайн-кінотеатр: каталог фільмів, кошик, замовлення, оплата Stripe. Навчальний проєкт, але з продакшн-дисципліною.

**Стек:** Python 3.12 · FastAPI · SQLAlchemy 2.0 (async, `Mapped`/`mapped_column`) · asyncpg · Alembic · PostgreSQL 16 · Pydantic v2 · Redis · Celery + celery-beat · MinIO · Stripe · Poetry · Docker Compose · pytest + pytest-asyncio · mypy strict · ruff + black.

**Напрям імпортів — односторонній:**
```
api/ → services/ → repositories/ → models/
```
- `AsyncSession` існує **тільки** в `repositories/` і `db/`
- `fastapi` **ніколи** не імпортується в `services/`
- Хендлер роута ≤ 10 рядків: залежності → один виклик сервісу → return
- Зовнішні системи (SMTP, S3, Stripe) — тільки через ABC в `integrations/`

**Іменування:** репозиторії `get_*`/`list_*`/`create_*`/`update_*`/`delete_*`/`exists_*`/`count_*`. Сервіси — сценарії: `register_user`, `place_order`. Схеми з суфіксом ролі: `MovieCreateSchema`, `MovieDetailSchema`. Вхідну схему ніколи не використовують як вихідну.

**Розміри:** модуль ≤ 300 рядків, клас ≤ 150, функція ≤ 40.

**Гроші:** `Decimal` наскрізно, `NUMERIC(10,2)` у БД. Арифметика на `float` заборонена. Час — `TIMESTAMP WITH TIME ZONE`, UTC.

---

## 2. БЛОК ЗАБОРОН (копіюй у КОЖНУ картку без змін)

```
ЗАБОРОНЕНО:
- Синхронний SQLAlchemy (Session, create_engine, query()). Тільки async: AsyncSession,
  create_async_engine, select(), Mapped[], mapped_column().
- Стара декларативна форма Column(...) без Mapped[] анотації.
- Pydantic v1 (class Config, @validator, orm_mode). Тільки v2:
  model_config = ConfigDict(...), @field_validator, from_attributes=True.
- raise HTTPException будь-де. Тільки винятки з core/exceptions.py.
- os.getenv / os.environ поза core/config.py.
- Імпорт fastapi всередині services/, repositories/, models/.
- float для грошей. Тільки Decimal.
- datetime.utcnow(). Тільки datetime.now(timezone.utc).
- Створення файлів, не вказаних у задачі.
- Заглушки TODO / pass / "тут буде реалізація". Код має бути повним.
- Пояснювальний текст поза кодом. Віддавай тільки вміст файлів.

ОБОВʼЯЗКОВО:
- Повні анотації типів, включно з типом повернення (проходить mypy --strict).
- Docstring на кожному публічному класі й функції, англійською.
- Якщо потрібен модуль, якого ще немає — не вигадуй його вміст, а імпортуй за
  вказаним у задачі шляхом і сигнатурою.
```

---

## 3. ЗАДАЧІ ДЛЯ БЕЗКОШТОВНИХ МОДЕЛЕЙ

### F0.1 — Конфігурація залежностей
**Файли:** `pyproject.toml`, `.env.sample`

`pyproject.toml` — Poetry, Python `^3.12`, пакет `src`.

Група `main`: fastapi, uvicorn[standard], sqlalchemy[asyncio], asyncpg, alembic, pydantic, pydantic-settings, pyjwt, passlib[bcrypt], python-multipart, celery, redis, jinja2, aiosmtplib, boto3, stripe, pillow.

Група `dev`: pytest, pytest-asyncio, pytest-cov, httpx, aiosqlite, ruff, black, mypy, faker, polyfactory, types-passlib.

Конфіги інструментів у тому ж файлі:
- `[tool.ruff]` — line-length 88, select `E,F,I,B,UP,SIM,C4,ANN`, target py312
- `[tool.black]` — line-length 88
- `[tool.mypy]` — `strict = true`, `plugins = ["pydantic.mypy"]`, ignore missing imports для `stripe`, `passlib`
- `[tool.pytest.ini_options]` — `asyncio_mode = "auto"`, `testpaths = ["tests"]`, маркери `unit`, `integration`, `e2e`
- `[tool.coverage.run]` — source `src`, omit міграцій

`.env.sample` — кожна змінна з плейсхолдером і коментарем-описом:
```
POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_HOST, POSTGRES_PORT
SECRET_KEY_ACCESS, SECRET_KEY_REFRESH, JWT_ALGORITHM
ACCESS_TOKEN_TTL_MINUTES, REFRESH_TOKEN_TTL_DAYS
ACTIVATION_TOKEN_TTL_HOURS, PASSWORD_RESET_TTL_MINUTES
EMAIL_HOST, EMAIL_PORT, EMAIL_USER, EMAIL_PASSWORD, EMAIL_FROM, EMAIL_USE_TLS
REDIS_URL, CELERY_BROKER_URL, CELERY_RESULT_BACKEND
S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET_NAME
STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_SUCCESS_URL, STRIPE_CANCEL_URL
ENVIRONMENT, DOCS_ENABLED
```
Реальних секретів не вписувати.

---

### F0.2 — Контейнеризація
**Файли:** `docker-compose.yml`, `docker/web/Dockerfile`, `docker/entrypoint.sh`

Сервіси: `db` (postgres:16-alpine, healthcheck `pg_isready`, іменований volume), `redis` (redis:7-alpine, healthcheck), `minio` (консоль 9001, volume), `mailhog` (1025/8025), `web`, `celery-worker`, `celery-beat`.

Вимоги:
- `web`, `celery-worker`, `celery-beat` збираються з одного Dockerfile, різняться `command`
- `depends_on` з `condition: service_healthy` для `db` і `redis`
- `env_file: .env` скрізь
- код змонтовано томом для гарячого перезавантаження в dev
- `web` публікує 8000

`Dockerfile` — багатоетапний: етап `builder` ставить Poetry й експортує залежності, фінальний етап — slim-образ,非-root користувач, без Poetry всередині.

`entrypoint.sh` — чекає доступності Postgres у циклі, виконує `alembic upgrade head`, стартує uvicorn.

---

### F0.3 — Ієрархія доменних винятків
**Файл:** `src/core/exceptions.py`

Базовий `AppError(Exception)`: приймає `message: str` і `details: dict[str, Any] | None = None`, зберігає їх атрибутами, передає `message` у `super().__init__`.

Нащадки, кожен із власним дефолтним повідомленням:

| Клас | Дефолтне повідомлення |
|---|---|
| `ValidationError` | Validation failed. |
| `NotFoundError` | Requested resource was not found. |
| `ConflictError` | Resource conflict. |
| `AuthenticationError` | Authentication failed. |
| `PermissionDeniedError` | Not enough permissions. |
| `TokenExpiredError` | Token has expired. |
| `ExternalServiceError` | External service is unavailable. |

Жодних імпортів FastAPI чи Starlette. Мапінг у HTTP-коди робиться поза цим модулем.

---

### F0.4 — Тести фундаменту
**Файли:** `tests/unit/test_config.py`, `tests/integration/test_db_session.py`, `tests/e2e/test_health.py`

Модулі, яких ще немає — імпортуй за цими сигнатурами:
```python
from src.core.config import Settings, get_settings   # get_settings() -> Settings
from src.db.session import get_session               # async generator -> AsyncSession
from src.main import create_app                      # () -> FastAPI
```

`test_config.py`:
- `get_settings()` повертає `Settings`, повторний виклик віддає той самий обʼєкт (кешування)
- при відсутності обовʼязкової змінної оточення створення `Settings` кидає `ValidationError` від Pydantic
- **ключовий тест:** множина полів `Settings.model_fields` збігається з множиною ключів, розпарсених із `.env.sample` (ігноруючи коментарі та порожні рядки, порівняння без урахування регістру)

`test_db_session.py`:
- `get_session` віддає працюючу `AsyncSession`, простий `SELECT 1` повертає 1
- **ізоляція:** два окремі тести вставляють рядок з тим самим унікальним значенням у тимчасову таблицю — обидва мають пройти, що доводить відкат між тестами

`test_health.py`:
- `GET /health` → 200, тіло рівно `{"status": "ok"}`
- неіснуючий шлях → 404

Тести асинхронні, HTTP — через `httpx.AsyncClient` з `ASGITransport`. Фікстури `async_client` і `db_session` вважай наявними в `conftest.py` — оголошувати їх не треба, лише використовувати.

---

## 4. БЛОК C0 — ВИКОНУЄ CLAUDE PRO САМОСТІЙНО

Не віддавати безкоштовним моделям: тут async-інфраструктура й фікстури з відкотом, де вони стабільно помиляються.

**`src/core/config.py`**
`Settings(BaseSettings)` — плоский клас із групуванням через префікси, `model_config = SettingsConfigDict(env_file=".env", extra="forbid")`. Обчислювані властивості: `database_url` (asyncpg DSN зі складників) і `sync_database_url` для Alembic. `get_settings()` під `@lru_cache`. Це єдине місце в проєкті, де читається оточення.

**`src/db/base.py`**
`Base(DeclarativeBase)` із `metadata = MetaData(naming_convention=...)` — конвенція для `ix/uq/ck/fk/pk` обовʼязкова, інакше Alembic autogenerate шумітиме. Міксини: `IntPKMixin` (`id: Mapped[int]`), `TimestampMixin` (`created_at`, `updated_at`, timezone-aware, server-side default), `TokenMixin` (`token: Mapped[str]` unique indexed, `expires_at: Mapped[datetime]`, метод `is_expired`).

**`src/db/session.py`**
`create_async_engine` з `pool_pre_ping=True`, `async_sessionmaker(expire_on_commit=False)`, залежність `get_session` — генератор, що комітить при успіху, робить rollback при винятку й завжди закриває сесію.

**`src/main.py`**
Тільки `create_app()`: інстанс FastAPI, CORS, реєстрація обробників винятків (мапінг `AppError`-ієрархії на коди 422/404/409/401/403/400/502 — рівно одне місце в проєкті), `GET /health`, підключення `api/v1/router.py` (поки порожній агрегатор).

**`tests/conftest.py`**
Двигун — session-scoped. Кожен тест: `connection.begin()` → `begin_nested()` → сесія прив’язана до цього зʼєднання → `rollback()` після тесту. Перевизначення `app.dependency_overrides[get_session]`. Фікстура `async_client` на `ASGITransport`. Створення схеми — один раз на сесію.

**Alembic**
`alembic init -t async`, `env.py` тягне `Base.metadata` і URL із `Settings`, `compare_type=True`, `render_as_batch=False`.

**Завершення блоку:** усі тести з `F0.4` зелені, `ruff`/`black`/`mypy --strict src/` чисті.

---

## 5. ГЕЙТИ ПРИЙМАННЯ ФАЗИ

- [ ] `docker compose up` з чистого клону піднімає всі 7 сервісів у healthy
- [ ] `pytest` — зелено, тестів не менше 8
- [ ] `mypy --strict src/` — 0 помилок
- [ ] `ruff check .` і `black --check .` — чисто
- [ ] `alembic revision --autogenerate` на порожніх моделях дає порожню міграцію
- [ ] `.env.sample` покриває 100 % полів `Settings` (доведено тестом)

Гілка `phase-00-foundation`. Комміти окремо: спочатку тести (червоні), потім реалізація.

---

## 6. ФОРМАТ ПЕРЕДАЧІ ДАЛІ

Наприкінці фази виведи блок для наступного чату — тільки сигнатури, без тіл функцій:

```
STATE-00
Створені модулі:
  src/core/config.py      — Settings(...поля...), get_settings() -> Settings
  src/core/exceptions.py  — AppError, ValidationError, NotFoundError, ConflictError,
                            AuthenticationError, PermissionDeniedError,
                            TokenExpiredError, ExternalServiceError
  src/db/base.py          — Base, IntPKMixin, TimestampMixin, TokenMixin
  src/db/session.py       — get_session()
  src/main.py             — create_app()
  tests/conftest.py       — фікстури: db_session, async_client, ...
Прийняті рішення, що впливають на наступні фази: <перелік>
Відомий технічний борг: <перелік або "немає">
```
