# PHASE 02 — Registration & Account Activation
### Hand-off package. Paste this entire document as the first message into a fresh Claude Pro chat.

---

## 0. EXECUTOR INSTRUCTIONS (read by Claude Pro in the new chat)

You are the executor for a single phase of the **Online Cinema** project (FastAPI backend). Phases 0 (foundation) and 1 (account models) are closed. You have two roles:

**Role 1 — card generator.** You produce copy-paste-ready task cards for free models (Gemini / DeepSeek / Grok). Each card must be self-contained: those models cannot see the repository or this document. Embed the ban block (§2) into every card verbatim.

**Role 2 — implementer.** After the user brings back the generated code, you review it, fix it, and write the `C2` block yourself.

**Working order:**

1. Emit card `F2.1`. Stop. Wait.
2. User returns code → short review (list violations, do not rewrite wholesale) → emit card `F2.2`. Continue through `F2.5`.
3. After `F2.5`, write the `C2` block yourself.
4. Finish with the `STATE-02` block (§7).

Emit cards **one at a time**. `F2.1`, `F2.3` and `F2.5` are mutually independent and may go to three different models in parallel. `F2.2` requires `F2.1` to be done. `F2.4` requires `F2.3`.

**This is the heaviest Pro-side phase in the project.** Two artifacts are born here — `BaseRepository` and the generic token-lifecycle helper — and every later phase depends on them. Their quality determines how much duplication phases 3–7 will be forced into. Do not rush them.

---

## 1. PROJECT CONTEXT

Online cinema: movie catalog, cart, orders, Stripe payments. Educational project held to production discipline.

**Stack:** Python 3.12 · FastAPI · SQLAlchemy 2.0 async · asyncpg · Alembic · PostgreSQL 16 · Pydantic v2 · Celery + celery-beat + Redis · pytest + pytest-asyncio · mypy strict · ruff + black.

**Import direction:** `api/ → services/ → repositories/ → models/`. `AsyncSession` lives only in `repositories/` and `db/`. `fastapi` is never imported inside `services/`. A route handler is ≤ 10 lines: dependencies in, one service call, return.

**External systems** (SMTP, S3, Stripe) are reached only through an ABC in `integrations/`. Services receive the interface by injection and never import a concrete implementation.

**Sizing:** module ≤ 300 lines, class ≤ 150, function ≤ 40. **Time:** UTC, `datetime.now(timezone.utc)`.

### 1.1 Current repository state (STATE-01, verbatim)

```
src/db/enums.py           UserGroupEnum(StrEnum): USER="user", MODERATOR="moderator",
                          ADMIN="admin"
                          GenderEnum(StrEnum): MAN="man", WOMAN="woman"

src/models/accounts.py    _enum_values(enum_class) -> Sequence[str]   # values_callable
                          UserGroup(user_groups): id, name: UserGroupEnum
                            (SQLEnum name="user_group_enum", unique); rel: users
                          User(users): id, email(255, unique, index),
                            hashed_password(255), is_active(default False,
                            server_default false()), created_at, updated_at,
                            group_id -> user_groups.id ondelete=RESTRICT
                            rels: group, profile, activation_token,
                                  password_reset_token, refresh_tokens
                          UserProfile(user_profiles): id, user_id(unique, CASCADE),
                            first_name(100), last_name(100), avatar(255),
                            gender: GenderEnum | None (SQLEnum name="gender_enum"),
                            date_of_birth: date, info: Text; rel: user
                          ActivationToken(activation_tokens): id, token, expires_at,
                            user_id(unique, CASCADE); rel: user
                          PasswordResetToken(password_reset_tokens): same,
                            user_id unique
                          RefreshToken(refresh_tokens): same, user_id NOT unique
                          (token / expires_at / is_expired come from TokenMixin)

src/models/__init__.py    re-export of all six models (__all__)

src/security/passwords.py BCRYPT_MAX_PASSWORD_BYTES = 72
                          hash_password(plain: str) -> str
                          verify_password(plain: str, hashed: str) -> bool

src/security/validators.py MIN_PASSWORD_LENGTH = 8, SPECIAL_CHARACTERS
                          validate_password_strength(password: str) -> None
                          normalize_email(email: str) -> str

src/db/seed/groups.py     ensure_default_groups(session: AsyncSession) -> None

src/core/config.py        Settings(...), get_settings() -> Settings
                          includes ACTIVATION_TOKEN_TTL_HOURS, EMAIL_HOST/PORT/USER/
                          PASSWORD/FROM/USE_TLS, CELERY_BROKER_URL,
                          CELERY_RESULT_BACKEND
src/core/exceptions.py    AppError, ValidationError, NotFoundError, ConflictError,
                          AuthenticationError, PermissionDeniedError,
                          TokenExpiredError, ExternalServiceError
                          __init__(message: str, details: dict | None = None)
src/db/base.py            Base, IntPKMixin, TimestampMixin,
                          TokenMixin(token, expires_at, is_expired)
src/db/session.py         get_session() -> AsyncGenerator[AsyncSession, None]
src/main.py               create_app() -> FastAPI

tests/conftest.py         fixtures: db_session, async_client
tests/factories/accounts.py create_group, create_user, create_profile,
                          create_activation_token, create_password_reset_token,
                          create_refresh_token   (async, flush without commit)

Alembic head: 6a6cc33214e6  (down_revision 9b003e04c6f1)
```

### 1.2 Binding decisions inherited from phase 1

These are not suggestions. Violating them breaks existing code or data consistency.

1. **Enums are `enum.StrEnum`**, not `str + Enum` — ruff rule UP042 forbids the double inheritance. Any new enum in this phase must follow suit.
2. **`SQLEnum` is constructed with `values_callable`**, so the database stores member *values* (`"user"`), not member *names* (`"USER"`). New enums must do the same or the data format across tables will diverge.
3. **Native enum type names are explicit** (`user_group_enum`, `gender_enum`). Keep naming new ones the same way.
4. **`passlib` was removed from dependencies.** Its 2020 release feeds bcrypt a 100-byte probe password and bcrypt ≥ 4.1 raises `ValueError`. Hashing calls `bcrypt` directly with `rounds=12`. Do not reintroduce passlib.
5. **The bcrypt 72-byte limit is handled explicitly.** `hash_password` raises `ValidationError` rather than silently hashing a truncated password, and `validate_password_strength` carries a matching rule. **Registration must call the validator before hashing.**
6. **`verify_password` returns `False` on a corrupt hash string** instead of raising, so a damaged row cannot turn login into a 500.
7. **Optional one-to-one relationships are annotated `Mapped["X | None"]`** — a user may have no profile and no token.
8. **`alembic/env.py` imports `src.models`.** Every new model must be reachable from `src/models/__init__.py` or autogenerate will not see it.
9. **Autogenerate does not drop native enum types.** Every migration that introduces an enum must issue a manual `DROP TYPE` in `downgrade()`.
10. **Factories flush and never commit.** Test isolation depends on the transaction rollback in the `db_session` fixture.
11. **Tests that expect a database constraint to fire delete rows with a Core `delete()` statement**, because the ORM would null the FK first and trip a different constraint.

### 1.3 Outstanding debt this phase must clear

- `ensure_default_groups` is defined but never called — wire it into application startup or a CLI command (part of block `C2`).
- No `.gitattributes`; files rewritten by Windows tooling to CRLF produce whole-file phantom diffs. Add one at the start of this phase.
- Branch `phase-01-accounts-models` was merged into `phase-00-foundation` and deleted, so the branch name no longer matches its contents. Rename to `main` before branching for this phase (see §6).

Still-open debt from phase 0 (not blocking, do not fix here unless trivial): permissive CORS, `sync_database_url` on psycopg2 for Alembic offline mode only, unused `aiosqlite`, no healthcheck on `celery-worker` / `celery-beat`.

---

## 2. BAN BLOCK (embed verbatim in EVERY card)

```
FORBIDDEN:
- Synchronous SQLAlchemy. Async only: AsyncSession, select(), Mapped[], mapped_column().
- Pydantic v1 idioms (class Config, @validator, orm_mode). v2 only:
  model_config = ConfigDict(from_attributes=True), @field_validator.
- raise HTTPException anywhere. Only exceptions from core/exceptions.py.
- os.getenv / os.environ outside core/config.py.
- Importing fastapi inside services/, repositories/, models/, integrations/.
- Business logic in schemas. Schemas validate shape, not domain rules.
- Any home-grown password strength check. Call
  src.security.validators.validate_password_strength instead.
- Importing or reintroducing passlib. Hashing already exists in
  src.security.passwords and must not be reimplemented.
- Concrete transport code (smtplib, aiosmtplib) inside an interface file.
- datetime.utcnow(). Use datetime.now(timezone.utc).
- str + Enum double inheritance. Use enum.StrEnum.
- Creating files not listed in the task.
- Placeholders: TODO, pass, "implementation goes here". Code must be complete.
- Prose outside the code. Return file contents only.

REQUIRED:
- Full type annotations including return types (must pass mypy --strict).
- A docstring on every public class and function, in English.
- If you need a module that does not exist yet, import it at the path and signature
  given in the task. Do not invent its contents.
```

---

## 3. TASKS FOR FREE MODELS

### F2.1 — Registration and activation schemas
**Files:** `src/schemas/common.py`, `src/schemas/accounts.py`

`common.py`:
- `MessageResponseSchema` — single field `message: str`

`accounts.py`:

| Schema | Fields | Notes |
|---|---|---|
| `UserRegistrationRequestSchema` | `email: EmailStr`, `password: str` | email validator applies `normalize_email`; password validator calls `validate_password_strength` |
| `UserRegistrationResponseSchema` | `id: int`, `email: EmailStr` | `from_attributes=True`; **must never expose password or hash** |
| `ActivationRequestSchema` | `email: EmailStr`, `token: str` | |
| `ResendActivationRequestSchema` | `email: EmailStr` | |

Requirements:
- `password` field constraints `min_length=8`, `max_length=128`
- every request schema sets `extra="forbid"` in `model_config`
- every schema carries `json_schema_extra` with an example — this surfaces in Swagger
- imports: `from src.security.validators import normalize_email, validate_password_strength`

The password validator must let the `ValidationError` from `core/exceptions.py` propagate — do not catch it or convert it into a `ValueError`.

---

### F2.2 — E2E tests for registration and activation
**File:** `tests/e2e/test_registration.py`

Fixtures `async_client` and `db_session` already exist. Endpoints under test (not yet written):

```
POST /api/v1/accounts/register/           -> 201  UserRegistrationResponseSchema
POST /api/v1/accounts/activate/           -> 200  MessageResponseSchema
POST /api/v1/accounts/resend-activation/  -> 200  MessageResponseSchema
```

Assume a `fake_email_sender` fixture exists in `conftest.py`. It collects sent messages in `sent: list[SentEmail]`, where `SentEmail` has `to: str`, `subject: str`, `body: str`.

**Registration**
- valid payload → 201; body carries `id` and `email`, and carries neither `password` nor `hashed_password`
- database now holds a user with `is_active=False` in group `USER`
- exactly one `ActivationToken` exists, `expires_at` ≈ now + 24 h (1-minute tolerance)
- exactly one email was sent to that address and its body contains the token value
- an email with mixed case and surrounding whitespace (`"  User@Mail.COM "`) is stored normalized
- registering the same email twice → 409; no second user row; **no second email sent**
- registering an email differing only in case → also 409
- weak passwords → 422, parametrized over: too short, no uppercase, no lowercase, no digit, no special character, **and over 72 bytes** (the bcrypt limit inherited from phase 1)
- malformed email → 422
- unexpected extra field in body → 422
- missing required field → 422

**Activation**
- valid token + matching email → 200; `is_active=True`; token row deleted
- reusing the same token → 400
- token whose `expires_at` is in the past → 400, and the message specifically indicates expiry
- token belonging to a different user → 400
- unknown token → 400
- activating an already-active account → 400
- empty `token` → 422

**Resend activation**
- inactive account with an expired token → 200; exactly one token row remains and it is new (value changed, `expires_at` extended); one email sent
- the previous token no longer activates → 400
- **already-active** account → 200 with a neutral message; no email sent; no token created
- **unknown** email → 200 with the **same** neutral message and status; no email sent
- dedicated test: the response bodies for the already-active case and the unknown-email case are **byte-identical** (account-existence disclosure guard)

Group tests into classes `TestRegistration`, `TestActivation`, `TestResendActivation`. Mark with `@pytest.mark.e2e`. Weak passwords go through `@pytest.mark.parametrize`, not six separate functions.

---

### F2.3 — Email sender interface and templates
**Files:** `src/integrations/email/interface.py`, `src/integrations/email/templates/activation_request.html`, `src/integrations/email/templates/activation_complete.html`

`interface.py` — abstraction only, zero network code:

```python
@dataclass(frozen=True)
class SentEmail:
    to: str
    subject: str
    body: str

class EmailSenderInterface(ABC):
    @abstractmethod
    async def send_activation_email(self, email: str, activation_link: str) -> None: ...
    @abstractmethod
    async def send_activation_complete_email(self, email: str, login_link: str) -> None: ...
```

Password-reset and order-confirmation methods arrive in later phases — do not declare them now.

Templates: self-contained HTML with inline CSS (mail clients ignore external stylesheets), Jinja2 placeholders.
- `activation_request.html` — `{{ email }}`, `{{ activation_link }}`, states the 24-hour validity, prominent link button, plain-text fallback showing the full URL
- `activation_complete.html` — `{{ email }}`, `{{ login_link }}`

600 px layout, table-based markup, no external images or scripts.

---

### F2.4 — Email test double
**File:** `tests/doubles/fake_email.py`

`FakeEmailSender(EmailSenderInterface)` — implements every interface method, sends nothing, appends `SentEmail` records to a public `sent` list.

Additional surface:
- `clear() -> None` — wipes history
- `last -> SentEmail | None` — most recent message
- `count_for(email: str) -> int` — messages sent to an address
- `raise_on_send: bool = False` — when `True`, any send raises `ExternalServiceError` (needed for degradation tests)

Subject lines are fixed strings defined inside the double, one per message type. Also create `tests/doubles/__init__.py`.

---

### F2.5 — Celery configuration
**File:** `src/tasks/celery_app.py`

A `Celery` application named `online_cinema`, broker and backend pulled from `get_settings()`.

Configuration: `task_serializer="json"`, `accept_content=["json"]`, `result_serializer="json"`, `timezone="UTC"`, `enable_utc=True`, `task_track_started=True`, `task_time_limit=300`.

`autodiscover_tasks(["src.tasks"])`.

One `beat_schedule` entry:
```
"purge-expired-activation-tokens": {
    "task": "src.tasks.tokens.purge_expired_activation_tokens",
    "schedule": crontab(minute=0),   # hourly
}
```

Do **not** create `src/tasks/tokens.py` — another party writes it. The module must import cleanly with no Redis running.

---

## 4. BLOCK C2 — CLAUDE PRO WRITES THIS PERSONALLY

Order matters: items 1–2 are the foundation reused by phases 3–7.

**1. `src/repositories/base.py` — `BaseRepository`**
Generic `BaseRepository(Generic[ModelT])` with `ModelT = TypeVar("ModelT", bound=Base)`. Constructor takes `session: AsyncSession` and the model class. Methods: `get_by_id`, `get_by`, `list`, `create`, `update`, `delete`, `exists`, `count`. All async, fully typed, passing `mypy --strict` with no `Any` in signatures. No commits inside — the session dependency owns the transaction. This is the only CRUD in the project; concrete repositories add **specialised queries only**.

**2. Token lifecycle — generic helper**
`src/services/accounts/tokens.py`: a service parametrised by the token model class, exposing `issue` (drop the user's existing token, create a new one with the given TTL), `verify` (look up by value, check owner and expiry, raise `TokenExpiredError` / `AuthenticationError`), `consume` (verify then delete), `purge_expired` (delete all expired rows). Activation, password reset (phase 4) and refresh tokens (phase 3) all use **this same helper**. Forking this logic in a later phase blocks merge. Token values come from `secrets.token_urlsafe(32)`.

**3. `src/repositories/accounts.py`**
`UserRepository(BaseRepository[User])` — `get_by_email` (eager-loading group and profile) and `email_exists`. Nothing else.

**4. Services**
`src/services/accounts/registration.py` — `register_user`: normalize email, uniqueness check → `ConflictError`, fetch the `USER` group, **call `validate_password_strength` before `hash_password`** (per inherited decision 5), create the user, issue the activation token, send the email through `EmailSenderInterface`. If sending fails the whole transaction rolls back and no user row survives.
`src/services/accounts/activation.py` — `activate_account` and `resend_activation`. For an active account and for an unknown email, `resend_activation` returns an **identical** response and performs no side effects.

**5. `src/integrations/email/smtp_sender.py`**
Implementation on `aiosmtplib` plus Jinja2 rendering of the `F2.3` templates. Transport failures are wrapped in `ExternalServiceError`. Links are built from settings, never hardcoded.

**6. `src/api/deps.py` and `src/api/v1/accounts.py`**
`deps.py`: `get_email_sender`, `get_registration_service`, `get_activation_service` — all dependency wiring lives here. `accounts.py`: three routes, each ≤ 10 lines, with `response_model`, `status_code`, and documented error codes in `responses`. Mount the router in `api/v1/router.py`.

**7. `src/tasks/tokens.py`**
Task `purge_expired_activation_tokens` — a thin wrapper that opens a session and delegates to `purge_expired` from item 2. No logic in the task. Unit test: deletes only expired rows, leaves valid ones, and is safe on an empty table.

**8. Clear inherited debt**
Wire `ensure_default_groups` into application startup (lifespan) or a CLI command. Add `.gitattributes` with `* text=auto eol=lf` to stop CRLF phantom diffs.

**9. Exception mapping check**
Confirm `ConflictError → 409`, `TokenExpiredError → 400`, `ValidationError → 422` are already mapped in `main.py` from phase 0, and that `details` reaches the response body.

---

## 5. ACCEPTANCE GATES

- [ ] every test from `F2.2` is green
- [ ] coverage of `src/services/accounts/` = 100 %
- [ ] exactly one CRUD implementation (`BaseRepository`) and one token helper exist in the project
- [ ] `grep -r "HTTPException" src/` returns nothing
- [ ] `grep -r "smtplib\|aiosmtplib" src/services/` returns nothing
- [ ] `grep -r "passlib" src/ pyproject.toml` returns nothing
- [ ] no test sends a real email; SMTP is unreachable during the run
- [ ] `mypy --strict src/` reports 0 errors; `ruff` and `black --check` clean
- [ ] `alembic revision --autogenerate` produces an empty migration
- [ ] Swagger lists all three endpoints with request/response models and codes 201/200/409/422/400
- [ ] `celery -A src.tasks.celery_app inspect registered` sees the purge task

---

## 6. GIT WORKFLOW — MANDATORY

**Before starting:** rename the current branch to `main` (phase-1 debt: the branch name no longer matches its contents).

**Create a dedicated branch for this phase and work only there:**

```
git checkout main
git pull
git checkout -b phase-02-registration-activation
```

Every phase gets its own branch. Never commit phase work directly to `main`; merge through a reviewed PR with a green pipeline.

**Commit format:** `<type>(<scope>): <imperative summary>`
Types: `feat`, `fix`, `test`, `refactor`, `chore`, `docs`, `ci`.
The summary line is ≤ 72 characters, imperative mood, no trailing period. When the change is not self-evident, add a body after a blank line explaining **why**, not what.

**Commit sequence is part of the TDD gate.** Tests are committed first, in a failing state, in a commit separate from the implementation. A pull request whose first implementation commit precedes its test commit is rejected.

Expected commit order for this phase:

```
chore(repo): add gitattributes to normalize line endings
feat(schemas): add registration and activation request schemas
test(accounts): add failing e2e tests for registration and activation
feat(integrations): add email sender interface and message templates
test(doubles): add fake email sender for isolated tests
feat(tasks): configure celery application and beat schedule
feat(repositories): add generic base repository
feat(accounts): add generic token lifecycle helper
feat(accounts): implement registration service
feat(accounts): implement activation and resend services
feat(integrations): implement smtp email sender
feat(api): expose registration and activation endpoints
feat(tasks): add expired activation token purge task
fix(db): wire default group seeding into application startup
```

Commit small and often. One commit per logical unit — do not batch unrelated files. Each message must be specific enough that `git log --oneline` alone explains the phase; `update code`, `fixes`, and `wip` are rejected.

---

## 7. HAND-OFF FORMAT

At the end of the phase emit this block. The user pastes it into the next phase's chat.

```
STATE-02
Modules created:
  src/schemas/common.py            — MessageResponseSchema
  src/schemas/accounts.py          — UserRegistrationRequestSchema,
                                     UserRegistrationResponseSchema,
                                     ActivationRequestSchema,
                                     ResendActivationRequestSchema
  src/repositories/base.py         — BaseRepository[ModelT]: <list method signatures>
  src/repositories/accounts.py     — UserRepository: get_by_email, email_exists
  src/services/accounts/tokens.py  — <exact generic helper signature: class,
                                     constructor, issue / verify / consume /
                                     purge_expired>
  src/services/accounts/registration.py — register_user(...)
  src/services/accounts/activation.py   — activate_account(...), resend_activation(...)
  src/integrations/email/interface.py   — EmailSenderInterface: <methods>, SentEmail
  src/integrations/email/smtp_sender.py — SMTPEmailSender
  src/api/deps.py                  — <list of dependencies>
  src/api/v1/accounts.py           — POST /register/, /activate/, /resend-activation/
  src/tasks/celery_app.py          — celery_app, beat_schedule
  src/tasks/tokens.py              — purge_expired_activation_tokens
  tests/doubles/fake_email.py      — FakeEmailSender
New conftest fixtures: <list>
Migration: <revision id>
Branch: phase-02-registration-activation, merged to main as <PR/commit>
Decisions affecting later phases: <list>
Known technical debt: <list or "none">
```
