# STATE-02 — Registration & Account Activation

Paste this block into the phase-3 chat.

```
STATE-02

Modules created:
  src/schemas/common.py            — MessageResponseSchema
  src/schemas/accounts.py          — _EmailNormalizingSchema (private base carrying the
                                     before-mode email validator),
                                     UserRegistrationRequestSchema,
                                     UserRegistrationResponseSchema,
                                     ActivationRequestSchema,
                                     ResendActivationRequestSchema
  src/repositories/base.py         — class BaseRepository[ModelT: Base]  (PEP 695)
                                     __init__(session: AsyncSession, model: type[ModelT])
                                     async get_by_id(entity_id: int) -> ModelT | None
                                     async get_by(**filters: object) -> ModelT | None
                                     async list(*, limit: int | None = None,
                                                offset: int | None = None,
                                                **filters: object) -> Sequence[ModelT]
                                     async create(**values: object) -> ModelT
                                     async update(instance: ModelT,
                                                  **values: object) -> ModelT
                                     async delete(instance: ModelT) -> None
                                     async exists(**filters: object) -> bool
                                     async count(**filters: object) -> int
  src/repositories/tokens.py       — TokenT = TypeVar("TokenT", ActivationToken,
                                       PasswordResetToken, RefreshToken)
                                     TokenRepository(BaseRepository[TokenT]):
                                       async delete_for_user(user_id: int) -> int
                                       async delete_expired(moment: datetime) -> int
                                     (both run as one bulk DML statement)
  src/repositories/accounts.py     — UserRepository(BaseRepository[User]):
                                       __init__(session)   # model fixed to User
                                       async get_by_email(email) -> User | None
                                         (selectinload group + profile)
                                       async email_exists(email) -> bool
  src/services/accounts/tokens.py  — class TokenLifecycleService[
                                       TokenT: (ActivationToken, PasswordResetToken,
                                                RefreshToken)]
                                     __init__(repository: TokenRepository[TokenT])
                                       # takes the REPOSITORY, not the session
                                     async issue(user_id: int,
                                                 ttl: timedelta) -> TokenT
                                     async verify(token_value: str,
                                                  user_id: int) -> TokenT
                                     async consume(token_value: str,
                                                   user_id: int) -> TokenT
                                     async revoke_for(user_id: int) -> int
                                     async purge_expired(now: datetime | None
                                                         = None) -> int
                                     TOKEN_ENTROPY_BYTES = 32
                                     raises AuthenticationError (unknown/foreign),
                                            TokenExpiredError (elapsed)
  src/services/accounts/links.py   — build_activation_link(activation_url, email, token)
  src/services/accounts/registration.py — RegistrationService(users, groups, tokens,
                                       email_sender, activation_ttl, activation_url)
                                     async register_user(email, password) -> User
  src/services/accounts/activation.py   — ActivationService(users, tokens, email_sender,
                                       activation_ttl, activation_url, login_url)
                                     async activate_account(email, token) -> None
                                     async resend_activation(email) -> None
  src/integrations/email/interface.py   — SentEmail(to, subject, body) frozen dataclass;
                                     EmailSenderInterface(ABC):
                                       async send_activation_email(email,
                                                                   activation_link)
                                       async send_activation_complete_email(email,
                                                                            login_link)
  src/integrations/email/smtp_sender.py — SMTPEmailSender(*, host, port, username,
                                       password, sender, use_tls)
                                     Jinja2 + aiosmtplib; wraps SMTPException and
                                     OSError in ExternalServiceError
  src/integrations/email/templates/     — activation_request.html,
                                          activation_complete.html
  src/api/deps.py                  — SessionDep, SettingsDep, EmailSenderDep,
                                     get_email_sender, get_registration_service,
                                     get_activation_service,
                                     RegistrationServiceDep, ActivationServiceDep
  src/api/v1/accounts.py           — POST /register/ (201), /activate/ (200),
                                     /resend-activation/ (200); prefix /accounts
  src/tasks/celery_app.py          — celery_app, beat_schedule
                                     ("purge-expired-activation-tokens", crontab(minute=0))
  src/tasks/tokens.py              — purge_expired_activation_tokens() -> int
  tests/doubles/fake_email.py      — FakeEmailSender(*, raise_on_send=False):
                                     sent, last, clear(), count_for(email)
  tests/e2e/accounts_support.py    — endpoint URLs, registration_payload, get_user,
                                     user_count, tokens_for, pending_user

Modules changed:
  src/core/exceptions.py           — + InvalidRequestError
  src/main.py                      — + InvalidRequestError -> 400; + lifespan seeding
  src/core/config.py               — + frontend_base_url; activation_url, login_url
  src/api/v1/router.py             — mounts the accounts router
  docker-compose.yml               — worker/beat now load src.tasks.celery_app
  docs/ARCHITECTURE.md             — error taxonomy gains InvalidRequestError

Modules deleted:
  src/core/celery_app.py           — duplicate Celery app; src/tasks/celery_app.py wins

New conftest fixtures:
  tests/conftest.py                — fake_email_sender; the app fixture now overrides
                                     get_email_sender as well as get_session
  tests/e2e/conftest.py            — seed_user_group (autouse; ASGITransport does not
                                     run the lifespan that seeds groups in production)

Migration: none. No model changed, so alembic autogenerate must stay empty.

Branch: phase-02-registration-activation (21 commits off main, not yet merged)

Decisions affecting later phases:
  1. InvalidRequestError -> 400 is the error for a well-formed request the current
     state forbids. AuthenticationError stays 401 and means credentials.
  2. TokenLifecycleService takes a TokenRepository, never an AsyncSession. Phases 3
     and 4 construct TokenRepository(session, RefreshToken/PasswordResetToken) and
     reuse the same service. Do not fork it.
  3. issue() deletes every existing token for the user first. Refresh tokens in
     phase 3 are the one model where a user may legitimately hold several at once —
     if phase 3 needs concurrent sessions, add a flag to issue(), do not copy it.
  4. Generic classes use PEP 695 syntax; ruff UP046 rejects Generic[...] subclassing.
  5. Bulk deletes belong in a concrete repository, not in BaseRepository.
  6. Services receive collaborators by constructor injection; all wiring is in
     src/api/deps.py.
  7. Password strength is validated BEFORE hashing, in the service, not the schema
     alone.
  8. Email normalisation happens in a before-mode field validator so that a value
     with whitespace or mixed case reaches EmailStr already canonical.

Known technical debt:
  1. email-validator must be added to the dependencies (poetry add email-validator);
     EmailStr does not import without it. Not done here because poetry was not
     available in the authoring environment.
  2. mypy --strict was verified on a transform of the two PEP 695 classes into the
     classic Generic form (the authoring environment had no Python 3.12). Re-run
     mypy --strict src/ before merging.
  3. The e2e suite and the alembic autogenerate check were never executed: no
     PostgreSQL was reachable. They are the first thing to run.
  4. tests/integration/test_accounts_models.py is 411 lines, over the 300-line cap.
     Inherited from phase 1.
  5. The acceptance gate 'grep -r "passlib" src/' still matches one docstring in
     src/security/passwords.py that explains why passlib is not used. Scope the
     grep to imports, or accept the match.
  6. test_token_purge.py landed after its implementation, not before it.
  7. Still open from phase 0: permissive CORS, unused aiosqlite, no healthcheck on
     celery-worker / celery-beat.
```

## Gates still to run on a machine with the stack up

```bash
poetry add email-validator          # blocks everything below
docker compose up -d db redis mailhog
poetry run ruff check src tests     # verified clean
poetry run black --check src tests  # verified clean
poetry run mypy --strict src/       # verified on an equivalent transform only
poetry run pytest -q                # NOT RUN — no PostgreSQL available
poetry run pytest --cov=src --cov-report=term-missing
poetry run alembic revision --autogenerate -m "check empty"   # must be empty
poetry run celery -A src.tasks.celery_app inspect registered  # needs a worker up
```
