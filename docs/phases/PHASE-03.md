# PHASE 03 — JWT Authentication
### Hand-off package. Paste this entire document as the first message into a fresh Claude Pro chat.

---

## 0. EXECUTOR INSTRUCTIONS (read by Claude Pro in the new chat)

You are the executor for a single phase of the **Online Cinema** project (FastAPI backend). Phases 0 (foundation), 1 (account models) and 2 (registration & activation) are closed and merged to `main`. You have two roles:

**Role 1 — card generator.** You produce copy-paste-ready task cards for free models (Gemini / DeepSeek / Grok). Each card must be self-contained: those models cannot see the repository or this document. Embed the ban block (§2) into every card verbatim.

**Role 2 — implementer.** After the user brings back the generated code, you review it, fix it, and write the `C3` block yourself.

**Working order:**

1. Emit card `F3.1`. Stop. Wait.
2. User returns code → short review (list violations, do not rewrite wholesale) → emit card `F3.2`. Continue through `F3.4`.
3. After `F3.4`, write the `C3` block yourself.
4. Finish with the `STATE-03` block (§7).

Emit cards **one at a time**. `F3.1` and `F3.4` are independent of everything else and may go out in parallel. `F3.2` and `F3.3` require `F3.1` to be done.

**This phase has one genuine design trap.** The refresh token must be persisted, but the `token` column inherited from `TokenMixin` may be too narrow for a JWT string. §4 item 1 tells you how to resolve it. Verify the actual column definition before writing anything.

---

## 1. PROJECT CONTEXT

Online cinema: movie catalog, cart, orders, Stripe payments. Educational project held to production discipline.

**Stack:** Python 3.12 · FastAPI · SQLAlchemy 2.0 async · asyncpg · Alembic · PostgreSQL 16 · Pydantic v2 · Celery + celery-beat + Redis · PyJWT · pytest + pytest-asyncio · mypy strict · ruff + black.

**Import direction:** `api/ → services/ → repositories/ → models/`. `AsyncSession` lives only in `repositories/` and `db/`. `fastapi` is never imported inside `services/`. A route handler is ≤ 10 lines: dependencies in, one service call, return.

**Sizing:** module ≤ 300 lines, class ≤ 150, function ≤ 40. **Time:** UTC, `datetime.now(timezone.utc)`.

### 1.1 Current repository state (STATE-02, verbatim)

```
src/schemas/common.py       MessageResponseSchema
src/schemas/accounts.py     _EmailNormalizingSchema (private base carrying the
                              before-mode email validator)
                            UserRegistrationRequestSchema,
                            UserRegistrationResponseSchema,
                            ActivationRequestSchema, ResendActivationRequestSchema

src/repositories/base.py    class BaseRepository[ModelT: Base]        # PEP 695
                              __init__(session: AsyncSession, model: type[ModelT])
                              async get_by_id(entity_id: int) -> ModelT | None
                              async get_by(**filters: object) -> ModelT | None
                              async list(*, limit=None, offset=None,
                                         **filters: object) -> Sequence[ModelT]
                              async create(**values: object) -> ModelT
                              async update(instance, **values) -> ModelT
                              async delete(instance: ModelT) -> None
                              async exists(**filters: object) -> bool
                              async count(**filters: object) -> int

src/repositories/tokens.py  TokenT = TypeVar("TokenT", ActivationToken,
                                             PasswordResetToken, RefreshToken)
                            TokenRepository(BaseRepository[TokenT]):
                              async delete_for_user(user_id) -> int
                              async delete_expired(moment) -> int
                            (both are a single bulk DML statement)

src/repositories/accounts.py UserRepository(BaseRepository[User]):
                              async get_by_email(email) -> User | None
                                (selectinload group + profile)
                              async email_exists(email) -> bool

src/services/accounts/tokens.py
                            class TokenLifecycleService[
                              TokenT: (ActivationToken, PasswordResetToken,
                                       RefreshToken)]
                              __init__(repository: TokenRepository[TokenT])
                                # the REPOSITORY, never the session
                              async issue(user_id, ttl: timedelta) -> TokenT
                              async verify(token_value, user_id) -> TokenT
                              async consume(token_value, user_id) -> TokenT
                              async revoke_for(user_id) -> int
                              async purge_expired(now=None) -> int
                              TOKEN_ENTROPY_BYTES = 32
                              raises AuthenticationError (unknown / foreign),
                                     TokenExpiredError (elapsed)

src/services/accounts/links.py         build_activation_link(activation_url, email, token)
src/services/accounts/registration.py  RegistrationService(users, groups, tokens,
                                         email_sender, activation_ttl, activation_url)
                                       async register_user(email, password) -> User
src/services/accounts/activation.py    ActivationService(users, tokens, email_sender,
                                         activation_ttl, activation_url, login_url)
                                       async activate_account(email, token) -> None
                                       async resend_activation(email) -> None

src/integrations/email/interface.py    SentEmail(to, subject, body) frozen dataclass
                                       EmailSenderInterface(ABC):
                                         async send_activation_email(email,
                                                                     activation_link)
                                         async send_activation_complete_email(
                                                                 email, login_link)
src/integrations/email/smtp_sender.py  SMTPEmailSender(*, host, port, username,
                                         password, sender, use_tls)
                                       Jinja2 + aiosmtplib; wraps SMTPException and
                                       OSError in ExternalServiceError
src/integrations/email/templates/      activation_request.html, activation_complete.html

src/api/deps.py             SessionDep, SettingsDep, EmailSenderDep,
                            get_email_sender, get_registration_service,
                            get_activation_service,
                            RegistrationServiceDep, ActivationServiceDep
src/api/v1/accounts.py      POST /register/ (201), /activate/ (200),
                            /resend-activation/ (200); prefix /accounts
src/api/v1/router.py        mounts the accounts router

src/tasks/celery_app.py     celery_app, beat_schedule
                            ("purge-expired-activation-tokens", crontab(minute=0))
src/tasks/tokens.py         purge_expired_activation_tokens() -> int

src/core/exceptions.py      AppError, ValidationError, InvalidRequestError, NotFoundError,
                            ConflictError, AuthenticationError, PermissionDeniedError,
                            TokenExpiredError, ExternalServiceError
src/core/config.py          Settings(...), get_settings(); + frontend_base_url,
                            activation_url, login_url
src/main.py                 create_app(); InvalidRequestError -> 400; lifespan seeds groups

src/db/base.py              Base, IntPKMixin, TimestampMixin,
                            TokenMixin(token, expires_at, is_expired)
src/db/session.py           get_session()
src/db/enums.py             UserGroupEnum(StrEnum), GenderEnum(StrEnum)
src/models/accounts.py      UserGroup, User, UserProfile, ActivationToken,
                            PasswordResetToken, RefreshToken
src/security/passwords.py   BCRYPT_MAX_PASSWORD_BYTES = 72, hash_password,
                            verify_password (returns False on a corrupt hash)
src/security/validators.py  validate_password_strength, normalize_email

tests/conftest.py           db_session, async_client, fake_email_sender; the app
                            fixture overrides get_session and get_email_sender
tests/e2e/conftest.py       seed_user_group (autouse; ASGITransport does not run the
                            lifespan that seeds groups in production)
tests/doubles/fake_email.py FakeEmailSender(*, raise_on_send=False): sent, last,
                            clear(), count_for(email)
tests/e2e/accounts_support.py endpoint URLs, registration_payload, get_user,
                            user_count, tokens_for, pending_user
tests/factories/accounts.py create_group, create_user, create_profile,
                            create_activation_token, create_password_reset_token,
                            create_refresh_token  (async, flush without commit)

Alembic head: 6a6cc33214e6.  Phase 2 added no migration; autogenerate diff verified empty.
Gates at end of phase 2: ruff, black, mypy --strict (41 files), pytest 86/86.
```

### 1.2 Binding decisions inherited from phases 1–2

Violating any of these breaks existing code. They are not open for reinterpretation.

1. **`InvalidRequestError` → 400** is the error for a well-formed request that the current state forbids. **`AuthenticationError` → 401** means credentials. Pick correctly in this phase: bad password is 401, inactive account is 403.
2. **`TokenLifecycleService` takes a `TokenRepository`, never an `AsyncSession`.** This phase constructs `TokenRepository(session, RefreshToken)` and reuses the same service. **Do not fork it.**
3. **`issue()` currently deletes every existing token for the user first.** Refresh tokens are the one model where a user may legitimately hold several at once. If this phase needs concurrent sessions, **add a keyword flag to `issue()` — do not copy the method.** See §4 item 2.
4. Generic classes use **PEP 695** syntax; ruff UP046 rejects `Generic[...]` subclassing.
5. **Bulk deletes belong in a concrete repository**, not in `BaseRepository`.
6. **All dependency wiring lives in `src/api/deps.py`.**
7. Password strength is validated **before** hashing, in the service.
8. Email normalisation is a **before-mode** field validator, so the value reaches `EmailStr` already canonical.
9. Tests refresh rows with **`populate_existing`, never `expire_all`** — expiring the session invalidates objects the test still holds and the next attribute read raises `MissingGreenlet`.
10. Enums are `enum.StrEnum`; `SQLEnum` gets `values_callable`, so the database stores values, not member names.
11. `passlib` is not a dependency. Hashing is direct `bcrypt` with `rounds=12`. `hash_password` raises `ValidationError` above 72 bytes.
12. Every new model must be reachable from `src/models/__init__.py` or Alembic autogenerate will not see it.
13. Factories flush and never commit.

### 1.3 Operational notes carried forward

- **Never run the Alembic autogenerate gate straight after pytest.** The `_schema` fixture drops every table while `alembic_version` survives claiming head. Run `alembic stamp base && alembic upgrade head` first.
- `redis` publishes no host port in `docker-compose.yml` while `.env` points the broker at `redis://localhost:6379`, so celery commands only work inside the compose network. Fix it in this phase if it costs a single line; otherwise leave it.

### 1.4 Debt this phase must clear

- **No test covers the registration rollback when the mail transport fails.** `FakeEmailSender.raise_on_send` exists for exactly that and nothing calls it. This is task `F3.4` and it is the cheapest remaining route to 100 % coverage on `services/`.
- `tests/integration/test_accounts_models.py` is 411 lines, over the 300-line cap. Split it into model-scoped modules as part of this phase's cleanup commit.
- The gate `grep -r "passlib" src/` still matches a docstring in `src/security/passwords.py`. Reword the docstring so the gate is honest.
- `test_token_purge.py` landed after its implementation rather than before. Nothing to fix retroactively — do not repeat the pattern here.

Still open from phase 0, do not fix here: permissive CORS, unused `aiosqlite`, no healthcheck on `celery-worker` / `celery-beat`.

---

## 2. BAN BLOCK (embed verbatim in EVERY card)

```
FORBIDDEN:
- Synchronous SQLAlchemy. Async only: AsyncSession, select(), Mapped[], mapped_column().
- Pydantic v1 idioms (class Config, @validator, orm_mode). v2 only:
  model_config = ConfigDict(from_attributes=True), @field_validator.
- raise HTTPException anywhere. Only exceptions from core/exceptions.py.
- os.getenv / os.environ outside core/config.py.
- Importing fastapi inside services/, repositories/, models/, integrations/, security/.
- Business logic in schemas. Schemas validate shape, not domain rules.
- Reimplementing password hashing or strength validation. Both already exist in
  src/security/. Importing or reintroducing passlib.
- Writing a second token-lifecycle implementation. src/services/accounts/tokens.py
  already exists and is generic over the token model.
- Storing a raw JWT in a column without checking that column's declared length.
- datetime.utcnow(). Use datetime.now(timezone.utc).
- str + Enum double inheritance. Use enum.StrEnum.
- Generic[...] subclassing. Use PEP 695 syntax: class Foo[T: Bound]: ...
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

### F3.1 — Authentication schemas
**File:** `src/schemas/tokens.py`

| Schema | Fields | Notes |
|---|---|---|
| `LoginRequestSchema` | `email: EmailStr`, `password: str` | reuse `_EmailNormalizingSchema` from `src/schemas/accounts.py` as the base so normalisation stays in one place |
| `TokenPairResponseSchema` | `access_token: str`, `refresh_token: str`, `token_type: str = "bearer"` | |
| `AccessTokenResponseSchema` | `access_token: str`, `token_type: str = "bearer"` | |
| `RefreshRequestSchema` | `refresh_token: str` | `min_length=1` |
| `LogoutRequestSchema` | `refresh_token: str` | `min_length=1` |

Requirements:
- every request schema sets `extra="forbid"`
- every schema carries `json_schema_extra` with a realistic example
- **no password strength validation here** — login must accept whatever the user types and fail with 401, not 422. Only registration validates strength.
- `token_type` is a literal default, not a required input

---

### F3.2 — JWT manager unit tests
**File:** `tests/unit/test_jwt_manager.py`

The module under test does not exist yet. Import it at exactly this path and signature:

```python
from src.security.jwt_manager import JWTAuthManager, JWTAuthManagerInterface

manager = JWTAuthManager(
    secret_key_access="access-secret",
    secret_key_refresh="refresh-secret",
    algorithm="HS256",
    access_ttl=timedelta(minutes=15),
    refresh_ttl=timedelta(days=7),
)

manager.create_access_token(data: dict[str, Any]) -> str
manager.create_refresh_token(data: dict[str, Any]) -> str
manager.decode_access_token(token: str) -> dict[str, Any]
manager.decode_refresh_token(token: str) -> dict[str, Any]
```

Both decode methods raise `AuthenticationError` on an invalid token and `TokenExpiredError` on an elapsed one (both from `src.core.exceptions`).

Scenarios, marked `@pytest.mark.unit`:

- round trip: payload `{"user_id": 1}` encodes and decodes back with `user_id` intact
- the encoded payload carries `exp` and a token-type claim; access and refresh carry **different** type claims
- **cross-use is rejected:** a refresh token passed to `decode_access_token` raises `AuthenticationError`, and the reverse also raises
- **cross-secret is rejected:** a token minted with the access secret does not decode with the refresh secret
- a tampered token (flip one character in the payload segment) raises `AuthenticationError`
- a token signed with a different secret entirely raises `AuthenticationError`
- an already-expired token raises `TokenExpiredError`, not `AuthenticationError` — assert the exact type
- garbage input (`"not.a.token"`, empty string) raises `AuthenticationError`, never an unhandled `PyJWTError`
- access TTL is strictly shorter than refresh TTL for the configured manager
- `JWTAuthManager` is a subclass of `JWTAuthManagerInterface`

Freeze or inject time rather than sleeping. Do not use `time.sleep`.

---

### F3.3 — Authentication E2E tests
**File:** `tests/e2e/test_authentication.py`

Fixtures `async_client`, `db_session`, `seed_user_group` and helpers in `tests/e2e/accounts_support.py` already exist. Endpoints under test (not yet written):

```
POST /api/v1/accounts/login/    -> 201  TokenPairResponseSchema
POST /api/v1/accounts/refresh/  -> 200  AccessTokenResponseSchema
POST /api/v1/accounts/logout/   -> 200  MessageResponseSchema   (requires Bearer auth)
```

**Login**
- active user with correct password → 201, both tokens present and non-empty
- a `RefreshToken` row now exists for that user
- wrong password → 401
- unknown email → 401 with a body **byte-identical** to the wrong-password case (no account enumeration)
- **inactive (unactivated) account → 403**, and the message points at activation
- malformed email → 422
- missing field → 422
- extra field → 422
- email differing only in case or padded with whitespace still logs in

**Refresh**
- valid refresh token → 200 with a new access token
- the returned access token differs from the one issued at login
- a refresh token that is not in the database → 401
- an expired refresh token → 401
- an access token submitted to `/refresh/` → 401
- a syntactically valid but foreign-signed token → 401
- after the owning user is deactivated, refresh → 403

**Logout**
- authenticated logout with the matching refresh token → 200; that row disappears
- using the same refresh token afterwards → 401
- logout without an `Authorization` header → 401
- logout with a malformed header (`"Bearer"`, `"Token abc"`, `"abc"`) → 401, parametrized
- logout with a refresh token belonging to a different user → 401 and the victim's row survives

**Concurrent sessions**
- logging in twice produces two distinct refresh tokens and **both remain valid**
- logging out of one session leaves the other working — assert the second refresh still returns 200

**Protected-route probe**
- a temporary authenticated probe endpoint or an existing protected route returns 401 with no header, 401 with a bad token, and 200 with a fresh access token

Group into `TestLogin`, `TestRefresh`, `TestLogout`, `TestConcurrentSessions`. Mark `@pytest.mark.e2e`. Reuse `accounts_support.py` helpers; add new helpers there rather than duplicating setup.

---

### F3.4 — Registration rollback test (clears inherited debt)
**File:** `tests/e2e/test_registration_rollback.py`

`FakeEmailSender` already accepts `raise_on_send: bool`. When `True` every send raises `ExternalServiceError`. Nothing currently exercises this. Write the missing coverage.

Scenarios:
- registration attempted while the mail transport fails → response is 502
- **no `User` row survives** the failed attempt — assert by counting users before and after
- **no `ActivationToken` row survives**
- the same email can be registered successfully once the transport recovers (proves nothing was half-written)
- the failure message does not leak the SMTP host, port, or credentials

Use the existing `fake_email_sender` fixture and toggle `raise_on_send` inside the test. Helpers `user_count` and `tokens_for` already live in `tests/e2e/accounts_support.py`.

---

## 4. BLOCK C3 — CLAUDE PRO WRITES THIS PERSONALLY

**1. Resolve the refresh-token storage width — do this first.**
Inspect the `token` column declared on `TokenMixin` in `src/db/base.py`. A JWT with claims runs 200–400 characters; if the column is `String(255)` it will overflow in production while passing on short test payloads.

Choose and record the decision:
- **Preferred:** persist the **SHA-256 hex digest** of the refresh JWT (fixed 64 characters, fits any sane column, and a database leak yields no usable tokens). The client holds the JWT; the server hashes on lookup.
- Alternative: widen the column to `Text` and store the JWT verbatim. This costs a migration and leaves live credentials at rest in the database.

If you take the digest route, `TokenLifecycleService.issue()` must accept an optional explicit value instead of always generating one internally — add a keyword parameter, **do not fork the service** (inherited decision 2).

**2. Extend `TokenLifecycleService` for concurrent sessions.**
`issue()` currently revokes every existing token for the user. Add a keyword flag (for example `replace_existing: bool = True`) so login can issue additional refresh tokens without killing other sessions. Default stays `True` so activation and password reset are unaffected. Both new parameters from items 1 and 2 must be covered by unit tests.

**3. `src/security/jwt_manager.py`**
`JWTAuthManagerInterface` (ABC) plus `JWTAuthManager` implementing it, matching the signatures in `F3.2` exactly. Separate secrets for access and refresh, a token-type claim that makes cross-use impossible, `exp` and `iat` on every token. Every `PyJWT` exception is translated at this boundary: `ExpiredSignatureError → TokenExpiredError`, everything else → `AuthenticationError`. No `PyJWTError` escapes this module.

**4. `src/services/accounts/authentication.py`**
`AuthenticationService(users, refresh_tokens, jwt_manager, refresh_ttl)`:
- `login(email, password) -> tuple[str, str]` — normalize, fetch user, `verify_password`; wrong credentials and unknown email raise the **same** `AuthenticationError`; inactive account raises `PermissionDeniedError` (403)
- `refresh(refresh_token) -> str` — decode, verify the row exists and is unexpired, confirm the user is still active, mint a new access token
- `logout(user_id, refresh_token) -> None` — delete only that row; a token belonging to another user raises `AuthenticationError` and leaves the row intact

**5. `src/api/deps.py` — `get_current_user`**
The single authentication dependency for the entire project. Extracts the bearer token, decodes it as an **access** token, loads the user, rejects inactive users. Every later phase depends on this exact object; get it right now. Add `CurrentUserDep` alongside the existing `*Dep` aliases, plus `get_jwt_manager` and `get_authentication_service`.

**6. `src/api/v1/accounts.py`**
Three routes appended to the existing router, each ≤ 10 lines, with `response_model`, `status_code` and documented error codes in `responses`. `/login/` returns 201 (a session resource is created). Configure Swagger's security scheme so the "Authorize" button works.

**7. Cleanup commits (inherited debt)**
Split `tests/integration/test_accounts_models.py` into model-scoped modules under the 300-line cap. Reword the `passlib` docstring in `src/security/passwords.py` so `grep -r "passlib" src/` comes back empty. Publish the redis port in `docker-compose.yml` if it is a one-line change.

**8. Migration**
Only if you widened a column. Otherwise confirm the autogenerate diff is empty — after `alembic stamp base && alembic upgrade head`, per §1.3.

---

## 5. ACCEPTANCE GATES

- [ ] every test from `F3.2`, `F3.3` and `F3.4` is green
- [ ] coverage of `src/services/` = 100 %, `src/security/` = 100 %
- [ ] exactly one token-lifecycle implementation exists; `src/services/accounts/tokens.py` was extended, not copied
- [ ] `grep -r "HTTPException" src/` returns nothing
- [ ] `grep -r "passlib" src/` returns nothing
- [ ] `grep -rn "jwt\." src/ --include=*.py | grep -v security/jwt_manager.py` returns nothing — no PyJWT usage leaks out of the manager
- [ ] no test file exceeds 300 lines
- [ ] `mypy --strict src/` reports 0 errors; `ruff` and `black --check` clean
- [ ] `alembic revision --autogenerate` produces an empty migration (after `stamp base && upgrade head`)
- [ ] Swagger's Authorize button accepts a bearer token and protected routes respond 200
- [ ] logging in twice and logging out once leaves the other session alive (proven by test, not by inspection)

---

## 6. GIT WORKFLOW — MANDATORY

**One branch per phase. Branch from `main`, merge back into `main`, then delete the phase branch.** Do not carry a stale branch into the next phase — that is exactly how the phase-1 branch ended up holding phase-0 work.

**Start of phase:**
```
git checkout main
git pull
git checkout -b phase-03-jwt-authentication
```

**End of phase — merge, then delete:**
```
git checkout main
git merge --no-ff phase-03-jwt-authentication
git push origin main
git branch -d phase-03-jwt-authentication
git push origin --delete phase-03-jwt-authentication   # if it was pushed
```

`--no-ff` is required: it keeps the phase visible as a unit in the history. Merge only with a green pipeline. Record the resulting merge commit hash in `STATE-03`.

**Commit format:** `<type>(<scope>): <imperative summary>`
Types: `feat`, `fix`, `test`, `refactor`, `chore`, `docs`, `ci`. Summary ≤ 72 characters, imperative mood, no trailing period. Add a body after a blank line when the change is not self-evident — explain **why**, not what.

**Commit sequence is part of the TDD gate.** Tests are committed first, failing, in a commit separate from the implementation. A pull request whose first implementation commit precedes its test commit is rejected.

Expected commit order for this phase:

```
feat(schemas): add login, refresh and logout schemas
test(security): add failing unit tests for jwt manager
test(accounts): add failing e2e tests for login, refresh and logout
test(accounts): cover registration rollback on mail transport failure
refactor(accounts): allow token lifecycle to accept an explicit value
refactor(accounts): allow token lifecycle to keep existing tokens
feat(security): add jwt manager with separate access and refresh secrets
feat(accounts): implement authentication service
feat(api): add current user dependency
feat(api): expose login, refresh and logout endpoints
fix(accounts): restore registration rollback when mail delivery fails
test(accounts): split oversized model test module by bounded context
chore(security): reword passlib rationale to keep the grep gate honest
chore(docker): publish redis port for host side celery commands
```

Commit small and often, one logical unit per commit. Messages must be specific enough that `git log --oneline` alone explains the phase. `wip`, `fixes`, `update code` are rejected.

---

## 7. HAND-OFF FORMAT

```
STATE-03
Modules created:
  src/schemas/tokens.py            — LoginRequestSchema, TokenPairResponseSchema,
                                     AccessTokenResponseSchema, RefreshRequestSchema,
                                     LogoutRequestSchema
  src/security/jwt_manager.py      — JWTAuthManagerInterface, JWTAuthManager
                                     <exact constructor and method signatures>
  src/services/accounts/authentication.py — AuthenticationService
                                     <exact constructor and method signatures>
Modules changed:
  src/services/accounts/tokens.py  — <new issue() parameters and their defaults>
  src/api/deps.py                  — get_current_user, CurrentUserDep,
                                     get_jwt_manager, get_authentication_service
  src/api/v1/accounts.py           — POST /login/, /refresh/, /logout/
  <others>
Refresh token storage decision: <digest | widened column> and why
New conftest fixtures: <list>
Migration: <revision id or "none, autogenerate diff verified empty">
Branch: phase-03-jwt-authentication, merged to main as <hash> (--no-ff), branch deleted
Gates: ruff, black, mypy --strict (<n> files), pytest <n>/<n>, empty autogenerate diff
Decisions affecting later phases: <list>
Known technical debt: <list or "none">
```
