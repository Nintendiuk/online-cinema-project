STATE-01

Створені модулі:
  src/db/enums.py           — UserGroupEnum(StrEnum): USER="user", MODERATOR="moderator",
                              ADMIN="admin"; GenderEnum(StrEnum): MAN="man", WOMAN="woman"
  src/models/accounts.py    — _enum_values(enum_class) -> Sequence[str] (values_callable),
                              UserGroup(user_groups): id, name: UserGroupEnum
                                (SQLEnum name="user_group_enum", unique); users
                              User(users): id, email(255, unique, index),
                                hashed_password(255), is_active(default False,
                                server_default false()), created_at, updated_at,
                                group_id -> user_groups.id ondelete=RESTRICT;
                                звʼязки: group, profile, activation_token,
                                password_reset_token, refresh_tokens
                              UserProfile(user_profiles): id, user_id(unique, CASCADE),
                                first_name(100), last_name(100), avatar(255),
                                gender: GenderEnum | None (SQLEnum name="gender_enum"),
                                date_of_birth: date, info: Text; звʼязок user
                              ActivationToken(activation_tokens): id, token, expires_at,
                                user_id(unique, CASCADE); звʼязок user
                              PasswordResetToken(password_reset_tokens): те саме,
                                user_id unique
                              RefreshToken(refresh_tokens): те саме, user_id НЕ unique
                              (token/expires_at/is_expired приходять із TokenMixin)
  src/models/__init__.py    — реекспорт шести моделей (__all__)
  src/security/passwords.py — BCRYPT_MAX_PASSWORD_BYTES = 72,
                              hash_password(plain: str) -> str,
                              verify_password(plain: str, hashed: str) -> bool
  src/security/validators.py— MIN_PASSWORD_LENGTH = 8, SPECIAL_CHARACTERS,
                              validate_password_strength(password: str) -> None,
                              normalize_email(email: str) -> str
  src/db/seed/groups.py     — ensure_default_groups(session: AsyncSession) -> None
  tests/factories/accounts.py — create_group, create_user, create_profile,
                              create_activation_token, create_password_reset_token,
                              create_refresh_token (async, flush без commit)
  tests/integration/test_accounts_models.py (22), tests/integration/test_seed_groups.py (3),
  tests/unit/test_passwords.py (8), tests/unit/test_validators.py (12)

Міграція: 6a6cc33214e6 (down_revision 9b003e04c6f1)

Прийняті рішення, що впливають на наступні фази:
  - Енуми — enum.StrEnum (не str+Enum): ruff UP042 забороняє подвійне наслідування.
  - SQLEnum отримує values_callable, тому в БД лежать значення ("user"), а не імена
    членів ("USER"). Нові енуми в наступних фазах мають робити так само, інакше
    формат даних у різних таблицях розʼїдеться.
  - Імена нативних типів задані явно: user_group_enum, gender_enum.
  - passlib прибраний із залежностей: реліз 2020 року, його детектор бекенда передає
    bcrypt 100-байтний пароль, а bcrypt >= 4.1 кидає ValueError. Хешування — прямо
    через bcrypt (rounds=12). types-passlib і mypy-override теж прибрані.
  - Ліміт bcrypt у 72 байти обробляється явно: hash_password кидає ValidationError,
    а не хешує обрізаний пароль; validate_password_strength має відповідне правило.
    Реєстрація у фазі 2 має викликати валідатор ДО хешування.
  - verify_password повертає False на биту хеш-строку (не кидає), щоб зіпсований
    рядок не давав 500 на логіні.
  - Опційні one-to-one звʼязки анотовані Mapped["X | None"] — у користувача може
    не бути профілю чи токена.
  - alembic/env.py імпортує src.models; кожна нова модель має бути досяжною з
    src/models/__init__.py, інакше autogenerate її не побачить.
  - Autogenerate не дропає нативні enum-типи: downgrade() міграції робить DROP TYPE
    вручну. Це правило для всіх наступних міграцій з енумами.
  - Фабрики роблять flush і НЕ комітять — ізоляція тестів тримається на відкоті
    транзакції у фікстурі db_session.
  - Тести, що очікують падіння обмеження БД, видаляють рядки Core-стейтментом
    delete(...), інакше ORM спершу занулить FK і впаде не на тому обмеженні.

Відомий технічний борг:
  - Гілка phase-01-accounts-models злита у phase-00-foundation і видалена; назва
    гілки більше не відповідає вмісту — перейменувати на main.
  - Немає .gitattributes; файли, переписані Windows-інструментами на CRLF, дають
    фантомні діфи на весь файл.
  - ensure_default_groups ніде не викликається: підключити до старту застосунку
    або CLI-команди у фазі 2.
  - Ревізія 9b003e04c6f1 — порожня базова міграція без вмісту, лишена для цілісності
    ланцюга.
  - Борг фази 0 лишається чинним: відкритий CORS, sync_database_url на psycopg2
    (лише offline-режим alembic), aiosqlite невикористаний, celery-worker і
    celery-beat без healthcheck.
