# PHASE 01 — Акаунти: шар даних
### Пакет для передачі в новий чат Claude Pro. Вставити цілком, першим повідомленням.

---

## 0. ІНСТРУКЦІЯ ВИКОНАВЦЮ (читає Claude Pro в новому чаті)

Ти — виконавець однієї фази проєкту «Online Cinema» (FastAPI backend). Фаза 0 (фундамент) уже закрита. У тебе дві ролі:

**Роль 1 — генератор карток.** Формуєш готові до копіювання картки задач для безкоштовних моделей (Gemini / DeepSeek / Grok). Кожна картка самодостатня: модель не має доступу до репозиторію й не бачить цього документа. У картку вкладаєш блок заборон (§2) без змін.

**Роль 2 — імплементатор.** Після повернення коду ревʼюєш його, виправляєш і сам пишеш блок `C1`.

**Порядок роботи:**

1. Видай картку `F1.1`. Зупинись.
2. Користувач повертає код → коротке ревʼю (список порушень, не переписуй усе) → картка `F1.2`. І так до `F1.4`.
3. Після `F1.4` — сам пишеш блок `C1`.
4. Наприкінці видаєш `STATE-01` (формат у §6).

Картки видавай **по одній**. `F1.2` і `F1.3` можна віддати різним моделям паралельно — вони не залежать одна від одної, обидві спираються тільки на специфікацію нижче.

---

## 1. КОНТЕКСТ ПРОЄКТУ

Онлайн-кінотеатр: каталог фільмів, кошик, замовлення, оплата Stripe. Навчальний проєкт із продакшн-дисципліною.

**Стек:** Python 3.12 · FastAPI · SQLAlchemy 2.0 (async, `Mapped`/`mapped_column`) · asyncpg · Alembic · PostgreSQL 16 · Pydantic v2 · pytest + pytest-asyncio · mypy strict · ruff + black.

**Напрям імпортів:** `api/ → services/ → repositories/ → models/`. `AsyncSession` тільки в `repositories/` і `db/`. `fastapi` ніколи не імпортується в `services/`.

**Розміри:** модуль ≤ 300 рядків, клас ≤ 150, функція ≤ 40.

**Час:** `TIMESTAMP WITH TIME ZONE`, UTC, `datetime.now(timezone.utc)`.

### Що вже існує після фази 0

```
src/core/config.py      Settings(...), get_settings() -> Settings
src/core/exceptions.py  AppError, ValidationError, NotFoundError, ConflictError,
                        AuthenticationError, PermissionDeniedError,
                        TokenExpiredError, ExternalServiceError
                        (кожен: __init__(message: str, details: dict | None = None))
src/db/base.py          Base(DeclarativeBase) з naming_convention
                        IntPKMixin      -> id: Mapped[int]
                        TimestampMixin  -> created_at, updated_at (tz-aware)
                        TokenMixin      -> token: Mapped[str] (unique, indexed),
                                           expires_at: Mapped[datetime],
                                           is_expired -> bool
src/db/session.py       get_session() -> AsyncGenerator[AsyncSession, None]
src/main.py             create_app() -> FastAPI
tests/conftest.py       фікстури: db_session (AsyncSession з відкотом),
                        async_client (httpx.AsyncClient)
```

> **Користувачу:** якщо блок `STATE-00` з попереднього чату відрізняється від цього переліку — вставте його сюди замість цього блоку.

---

## 2. БЛОК ЗАБОРОН (копіюй у КОЖНУ картку без змін)

```
ЗАБОРОНЕНО:
- Синхронний SQLAlchemy (Session, create_engine, query()). Тільки async: AsyncSession,
  create_async_engine, select(), Mapped[], mapped_column().
- Стара форма Column(...) без Mapped[] анотації.
- Pydantic v1 (class Config, @validator, orm_mode). Тільки v2.
- raise HTTPException будь-де. Тільки винятки з core/exceptions.py.
- os.getenv / os.environ поза core/config.py.
- Імпорт fastapi всередині models/, repositories/, services/.
- Бізнес-логіка, хешування паролів чи валідація всередині models/. Моделі — це
  тільки колонки, звʼязки й обмеження БД.
- float для грошей. Тільки Decimal.
- datetime.utcnow(). Тільки datetime.now(timezone.utc).
- Дублювання колонок, які вже дає міксин із db/base.py.
- Створення файлів, не вказаних у задачі.
- Заглушки TODO / pass / "тут буде реалізація".
- Пояснювальний текст поза кодом. Віддавай тільки вміст файлів.

ОБОВʼЯЗКОВО:
- Повні анотації типів, включно з типом повернення (проходить mypy --strict).
- Docstring на кожному публічному класі й функції, англійською.
- Якщо потрібен модуль, якого ще немає — імпортуй за вказаним у задачі шляхом
  і сигнатурою, не вигадуй його вміст.
```

---

## 3. ЗАДАЧІ ДЛЯ БЕЗКОШТОВНИХ МОДЕЛЕЙ

### F1.1 — Перелічення
**Файл:** `src/db/enums.py`

Два `str`-енуми (`class X(str, Enum)`, щоб серіалізувалися в JSON без конвертації):

`UserGroupEnum`: `USER = "user"`, `MODERATOR = "moderator"`, `ADMIN = "admin"`.

`GenderEnum`: `MAN = "man"`, `WOMAN = "woman"`.

Значення фіксовані — вони потраплять у БД і в наступні фази. Модуль не імпортує нічого, крім `enum`.

---

### F1.2 — Моделі акаунтів
**Файл:** `src/models/accounts.py`

Імпорти бази: `from src.db.base import Base, IntPKMixin, TimestampMixin, TokenMixin`, енуми з `src.db.enums`.

**`UserGroup`** → таблиця `user_groups`
| Поле | Тип | Обмеження |
|---|---|---|
| `id` | int | PK (з `IntPKMixin`) |
| `name` | `UserGroupEnum` | `SQLEnum(UserGroupEnum)`, unique, not null |

Звʼязок: `users` — один-до-багатьох.

**`User`** → таблиця `users`
| Поле | Тип | Обмеження |
|---|---|---|
| `id` | int | PK |
| `email` | str(255) | unique, not null, indexed |
| `hashed_password` | str(255) | not null |
| `is_active` | bool | not null, default `False`, server_default false |
| `created_at`, `updated_at` | datetime tz | з `TimestampMixin` |
| `group_id` | int | FK `user_groups.id`, not null, `ondelete="RESTRICT"` |

Звʼязки:
- `group` → `UserGroup`, many-to-one
- `profile` → `UserProfile`, one-to-one, `uselist=False`, `cascade="all, delete-orphan"`
- `activation_token` → one-to-one, cascade delete-orphan
- `password_reset_token` → one-to-one, cascade delete-orphan
- `refresh_tokens` → one-to-many, cascade delete-orphan

**`UserProfile`** → таблиця `user_profiles`
| Поле | Тип | Обмеження |
|---|---|---|
| `id` | int | PK |
| `user_id` | int | FK `users.id`, **unique**, not null, `ondelete="CASCADE"` |
| `first_name` | str(100) | nullable |
| `last_name` | str(100) | nullable |
| `avatar` | str(255) | nullable (ключ у S3, не URL) |
| `gender` | `GenderEnum` | nullable |
| `date_of_birth` | date | nullable |
| `info` | Text | nullable |

**`ActivationToken`** → `activation_tokens`: `IntPKMixin` + `TokenMixin` + `user_id` FK `users.id` **unique**, not null, cascade.

**`PasswordResetToken`** → `password_reset_tokens`: те саме, `user_id` **unique**.

**`RefreshToken`** → `refresh_tokens`: `IntPKMixin` + `TokenMixin` + `user_id` FK `users.id` **НЕ unique** (у користувача може бути кілька активних сесій), not null, cascade.

Жодного повторного оголошення `token`/`expires_at` — вони приходять із `TokenMixin`. Додай `__repr__` кожній моделі. Не додавай методів із логікою.

---

### F1.3 — Інтеграційні тести моделей
**Файл:** `tests/integration/test_accounts_models.py`

Фікстура `db_session: AsyncSession` уже існує в `conftest.py` — просто використовуй. Усі тести async, маркер `@pytest.mark.integration`.

Групи сценаріїв:

**Групи користувачів**
- створення всіх трьох груп проходить; повторна вставка групи з тим самим `name` → `IntegrityError`
- `name` зберігається як значення енуму і читається назад як `UserGroupEnum`

**Користувач**
- створення користувача з існуючою групою проходить; `is_active` за замовчуванням `False`
- `created_at` і `updated_at` заповнені автоматично й timezone-aware (`tzinfo is not None`)
- дублікат `email` → `IntegrityError`
- `email` без групи (`group_id=None`) → `IntegrityError`
- спроба видалити групу, до якої привʼязаний користувач → помилка (RESTRICT)

**Профіль**
- один профіль на користувача створюється; другий профіль для того самого `user_id` → `IntegrityError`
- усі поля профілю опціональні: профіль лише з `user_id` створюється успішно
- `gender` приймає обидва значення `GenderEnum`

**Токени**
- створення `ActivationToken`, `PasswordResetToken`, `RefreshToken` для користувача
- другий `ActivationToken` для того самого користувача → `IntegrityError`
- другий `PasswordResetToken` для того самого користувача → `IntegrityError`
- **два** `RefreshToken` для того самого користувача створюються успішно
- дублікат значення `token` між рядками → `IntegrityError`
- `expires_at` timezone-aware
- `is_expired` повертає `True` для минулої дати і `False` для майбутньої

**Каскади**
- видалення користувача видаляє його профіль і всі три типи токенів
- видалення користувача не видаляє його `UserGroup`

Після операцій, що мають впасти, роби `await db_session.rollback()`, щоб сесія лишалась придатною.

---

### F1.4 — Фабрики для тестів
**Файл:** `tests/factories/accounts.py`

Без `factory_boy` — прості async-функції-білдери, бо сесія асинхронна.

```python
async def create_group(session, name: UserGroupEnum = UserGroupEnum.USER) -> UserGroup
async def create_user(session, *, email: str | None = None, password_hash: str = "hashed",
                      is_active: bool = True, group: UserGroup | None = None) -> User
async def create_profile(session, user: User, **overrides) -> UserProfile
async def create_activation_token(session, user: User, *, expires_in_hours: int = 24) -> ActivationToken
async def create_password_reset_token(session, user: User, *, expires_in_minutes: int = 30) -> PasswordResetToken
async def create_refresh_token(session, user: User, *, expires_in_days: int = 7) -> RefreshToken
```

Правила:
- `email=None` → генерувати унікальний через `faker` або лічильник, щоб паралельні виклики не конфліктували
- `group=None` → знайти або створити групу `USER` (get-or-create, без дублікатів)
- значення токенів — унікальні, через `secrets.token_urlsafe(32)`
- кожна функція робить `session.add`, `await session.flush()` і повертає обʼєкт із заповненим `id`. **Не комітити** — це зламає ізоляцію тестів
- усі функції повністю анотовані

Створи також `tests/factories/__init__.py` з реекспортом.

---

## 4. БЛОК C1 — ВИКОНУЄ CLAUDE PRO САМОСТІЙНО

**1. Ревʼю `F1.2`.** Типові порушення: повторне оголошення `token`/`expires_at` замість `TokenMixin`; `unique=True` забутий на `user_id` активації/скидання; `unique=True` помилково поставлений на `user_id` рефреш-токена; відсутній `ondelete` на FK; `Column()` замість `mapped_column()`. Виправ, не переписуючи файл цілком.

**2. `src/security/passwords.py`**
`hash_password(plain: str) -> str` і `verify_password(plain: str, hashed: str) -> bool` на `passlib.CryptContext` зі схемою bcrypt. Контекст — модульна константа, створюється один раз. Це єдине місце в проєкті, де відбувається хешування.

**3. `src/security/validators.py`**
`validate_password_strength(password: str) -> None` — кидає `ValidationError` із переліком усіх порушених правил у `details`, а не з першим-ліпшим. Правила: довжина ≥ 8, є велика літера, є мала, є цифра, є спецсимвол із набору `!@#$%^&*()-_=+[]{};:,.<>?/`.
`normalize_email(email: str) -> str` — trim + lower.
Обидві функції — єдине джерело правди; реєстрація, зміна й скидання пароля у фазах 2 і 4 викликають саме їх. Дублювання цієї логіки далі — блокує мердж.

**4. `src/db/seed/groups.py`**
`ensure_default_groups(session: AsyncSession) -> None` — ідемпотентно створює три групи, повторний запуск нічого не змінює. Викликається зі стартапу застосунку або CLI-команди.

**5. Юніт-тести на security** (пише Pro, бо покриття тут має бути 100 %): хеш не дорівнює plaintext; два хеші того самого пароля різні (сіль); `verify` істинний для правильного й хибний для неправильного; валідатор пропускає коректний пароль і кидає `ValidationError` на кожен із пʼяти дефектів окремо; `details` містить усі порушення, коли їх кілька; `normalize_email` обрізає пробіли й знижує регістр.

**6. Alembic**
Згенеруй міграцію, перевір, що `upgrade` на порожній БД дає схему, ідентичну метаданим (повторний autogenerate — порожній), і що `downgrade` відкатує без помилок. Порядок створення таблиць має враховувати FK.

---

## 5. ГЕЙТИ ПРИЙМАННЯ ФАЗИ

- [ ] `pytest` зелено, нових тестів ≥ 25
- [ ] покриття `src/security/` = 100 %
- [ ] `alembic upgrade head` → `alembic revision --autogenerate` дає порожню міграцію
- [ ] `alembic downgrade base` відпрацьовує без помилок
- [ ] `mypy --strict src/` — 0 помилок
- [ ] `ruff check .` і `black --check .` — чисто
- [ ] у `src/models/accounts.py` немає жодного методу з логікою і жодного імпорту `passlib`

Гілка `phase-01-accounts-models`. Спершу комміт із тестами (червоні), потім реалізація.

---

## 6. ФОРМАТ ПЕРЕДАЧІ ДАЛІ

```
STATE-01
Створені модулі:
  src/db/enums.py           — UserGroupEnum(USER|MODERATOR|ADMIN), GenderEnum(MAN|WOMAN)
  src/models/accounts.py    — UserGroup, User, UserProfile, ActivationToken,
                              PasswordResetToken, RefreshToken
                              (перелічи фактичні імена полів і звʼязків)
  src/security/passwords.py — hash_password(str) -> str, verify_password(str, str) -> bool
  src/security/validators.py— validate_password_strength(str) -> None,
                              normalize_email(str) -> str
  src/db/seed/groups.py     — ensure_default_groups(session) -> None
  tests/factories/accounts.py — create_group, create_user, create_profile,
                              create_activation_token, create_password_reset_token,
                              create_refresh_token
Міграція: <revision id>
Прийняті рішення, що впливають на наступні фази: <перелік>
Відомий технічний борг: <перелік або "немає">
```
