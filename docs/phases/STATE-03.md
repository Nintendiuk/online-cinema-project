# STATE-03 — JWT Authentication

> **Gate status: unverified.** `ruff`, `black --check` and the four grep gates are
> green. `mypy --strict`, `pytest` and the Alembic autogenerate diff have **not**
> been run — they need Python 3.12 and a live PostgreSQL. See §Runbook. Fill in
> the numbers below and delete this block before merging.

## Modules created

```
src/schemas/tokens.py
    LoginRequestSchema(_EmailNormalizingSchema)   email: EmailStr, password: str
    TokenPairResponseSchema                       access_token, refresh_token,
                                                  token_type = "bearer"
    AccessTokenResponseSchema                     access_token, token_type
    RefreshRequestSchema                          refresh_token: str (min_length=1)
    LogoutRequestSchema                           refresh_token: str (min_length=1)
    All request schemas set extra="forbid"; login runs no strength rules.

src/security/jwt_manager.py
    TOKEN_TYPE_CLAIM = "token_type"
    ACCESS_TOKEN_TYPE = "access"; REFRESH_TOKEN_TYPE = "refresh"
    refresh_token_digest(token: str) -> str          # sha256 hex, 64 chars
    JWTAuthManagerInterface(ABC)
        create_access_token(data: dict[str, Any]) -> str
        create_refresh_token(data: dict[str, Any]) -> str
        decode_access_token(token: str) -> dict[str, Any]
        decode_refresh_token(token: str) -> dict[str, Any]
    JWTAuthManager(JWTAuthManagerInterface)
        __init__(*, secret_key_access: str, secret_key_refresh: str,
                 algorithm: str, access_ttl: timedelta, refresh_ttl: timedelta)
        access_ttl / refresh_ttl                     # read-only properties
        every token carries token_type, jti, iat, exp
        ExpiredSignatureError -> TokenExpiredError
        every other PyJWTError -> AuthenticationError
        wrong token_type      -> AuthenticationError

src/services/accounts/authentication.py
    INVALID_CREDENTIALS_MESSAGE, INACTIVE_ACCOUNT_MESSAGE, INVALID_SESSION_MESSAGE
    AuthenticationService(users: UserRepository,
                          refresh_tokens: TokenLifecycleService[RefreshToken],
                          jwt_manager: JWTAuthManagerInterface,
                          refresh_ttl: timedelta)
        async login(email, password) -> tuple[str, str]
        async refresh(refresh_token) -> str
        async logout(user_id, refresh_token) -> None
```

## Modules changed

```
src/services/accounts/tokens.py
    issue(user_id, ttl, *, value: str | None = None,
          replace_existing: bool = True) -> TokenT
    Both defaults reproduce the phase-2 behaviour exactly; activation and
    password reset were not touched. Login passes value=<digest> and
    replace_existing=False.

src/api/deps.py
    bearer_scheme = HTTPBearer(scheme_name="BearerAccessToken", auto_error=False)
    MISSING_CREDENTIALS_MESSAGE, INVALID_ACCESS_TOKEN_MESSAGE
    get_jwt_manager -> JWTAuthManagerInterface        JWTAuthManagerDep
    get_authentication_service -> AuthenticationService
                                                      AuthenticationServiceDep
    get_current_user -> User                          CurrentUserDep
    CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, ...]

src/api/v1/accounts.py
    POST /login/   201 TokenPairResponseSchema     401 / 403 / 422
    POST /refresh/ 200 AccessTokenResponseSchema   401 / 403 / 422
    POST /logout/  200 MessageResponseSchema       401 / 403 / 422, Bearer required
    LOGOUT_COMPLETE_MESSAGE

src/security/passwords.py     module docstring reworded; grep gate now honest
docker-compose.yml            redis publishes 6379 on the host
tests/conftest.py             the app fixture's get_session override now applies
                              the production commit/rollback contract
tests/e2e/conftest.py         protected_probe fixture (throwaway guarded route)
tests/e2e/accounts_support.py LOGIN_URL, REFRESH_URL, LOGOUT_URL, PROBE_URL,
                              REFRESH_TTL_DAYS, login_payload, bearer,
                              app_jwt_manager, foreign_jwt_manager,
                              expired_jwt_manager, active_user, inactive_user,
                              store_refresh_token, refresh_tokens_for,
                              refresh_token_exists
```

## Refresh token storage decision

**SHA-256 digest.** `TokenMixin.token` is `String(255)`; a signed JWT with claims
runs 200-400 characters, so storing the token verbatim would pass on the short
payloads a test produces and overflow in production. The digest is a fixed 64
characters, needs no migration, and a database leak yields nothing a client could
present. The client holds the JWT; the server hashes on lookup.

Unsalted and deterministic, because the server has to find the row from the token
the client presents. Safe here: the input is a signed high-entropy JWT, not a
guessable secret.

`TokenLifecycleService.issue()` gained a `value` keyword to support this rather
than being forked (inherited decision 2).

## Test modules

| File | Covers |
|---|---|
| `tests/unit/test_jwt_manager.py` | round trip, type claims, cross-use, cross-secret, tampering, garbage, expiry, `jti` uniqueness |
| `tests/unit/test_refresh_token_digest.py` | digest width, stability, irreversibility |
| `tests/integration/test_token_lifecycle.py` | both new `issue()` keywords, and that their defaults are unchanged |
| `tests/e2e/test_authentication.py` | `TestLogin`, `TestRefresh` |
| `tests/e2e/test_sessions.py` | `TestLogout`, `TestConcurrentSessions` |
| `tests/e2e/test_route_guard.py` | `TestProtectedRoute` — `get_current_user` as a guard |
| `tests/e2e/test_registration_rollback.py` | the inherited debt from §1.4 |

`tests/integration/test_accounts_models.py` (411 lines) was split into
`test_user_group_model.py`, `test_user_model.py`, `test_user_profile_model.py`,
`test_token_models.py`, `test_account_cascades.py`, with the two builders moved to
`tests/integration/accounts_model_support.py`. Every module is now under the cap;
the longest in the repo is 287 lines.

## New conftest fixtures

`protected_probe` (`tests/e2e/conftest.py`) — mounts `GET /probe/` guarded by
`CurrentUserDep`. Not autouse; request it explicitly.

## Migration

**None.** The digest route needs no schema change. Confirm the autogenerate diff
is empty per §1.3 — `alembic stamp base && alembic upgrade head` **before**
`alembic revision --autogenerate`, never straight after pytest.

## Decisions affecting later phases

1. **`get_current_user` is the only authentication dependency.** Guard every
   protected route with `CurrentUserDep`. It rejects non-access tokens, unknown
   subjects and inactive accounts, and it never raises the framework's own web
   exception.
2. **An expired credential answers 401, not 400.** `TokenExpiredError` still maps
   globally to 400, which is right for a mistyped activation link. The
   authentication paths translate it to `AuthenticationError` at the point of use.
   Password reset in phase 4 should decide deliberately which of the two it wants.
3. **`HTTPBearer` must stay `auto_error=False`.** With the default it raises the
   framework exception directly and breaks the project's single-handler rule.
4. **Every token carries a random `jti`.** PyJWT serialises `iat`/`exp` as whole
   seconds, so two tokens minted for one user inside the same second would
   otherwise be byte-identical — and since the refresh row is keyed by the token's
   digest, the second login would collide on a unique index instead of opening a
   second session. Do not remove it.
5. **`replace_existing=False` is what makes concurrent sessions work.** Anything
   that issues refresh tokens must pass it. A future "log out everywhere" is the
   one caller that wants the default.
6. **The `app` fixture now enforces the transaction contract.** A request that
   raises rolls its writes back inside the test, as it does in production. Tests
   written against the old, looser behaviour may need adjusting.

## Known technical debt

- **The registration rollback was never broken in `src`.** `get_session` commits
  on success and rolls back on failure, correctly, since phase 2. What was missing
  was that the test double for it did neither, so the suite could not observe
  atomicity — a failed request left its flushed rows visible to the assertions
  that followed. The fix is in `tests/conftest.py`, and the commit is named
  `fix(tests): …` rather than the `fix(accounts): …` the phase document predicted.
- `AuthenticationService.logout` does not decode the JWT; it digests the string
  and looks the row up. A garbage value therefore fails as "unknown token" (401)
  rather than "malformed token". Same status code, cheaper path — recorded in case
  a later phase wants the distinction.
- Still open from phase 0, deliberately untouched: permissive CORS, unused
  `aiosqlite`, no healthcheck on `celery-worker` / `celery-beat`.

## Git

```
Branch: phase-03-jwt-authentication
Commits: 15 (1 docs, 4 test-first, 1 refactor, 4 feat, 1 fix, 1 test-split, 2 chore)
Merged to main as <hash> (--no-ff), branch deleted   <- fill in after the gates pass
```

## Runbook — gates still to run

PowerShell, from the repository root, virtualenv active. `&&` is not a statement
separator in PowerShell and `grep` does not exist there, so the commands below are
written for that shell rather than for bash.

**Always pass `tests` explicitly.** `testpaths` in `pyproject.toml` is ignored the
moment pytest is invoked without arguments from a rootdir it does not recognise —
a bare `pytest` once walked out of the project and tried to collect all of `C:\`,
producing ~1500 collection errors that had nothing to do with this phase.

```powershell
# 0. the venv must have a working pydantic. A bare `pytest tests` that reports
#    ModuleNotFoundError: No module named 'pydantic_core._pydantic_core'
#    means the binary wheel is broken, not that the tests are.
poetry install --sync
# or, without poetry:
pip install --force-reinstall --no-cache-dir pydantic pydantic-core

# 1. static (green as of this branch)
ruff check src tests
black --check src tests

# 2. types — needs Python 3.12; PEP 695 generics will not parse on anything older
mypy --strict src/

# 3. tests — needs the compose stack up
docker compose up -d db redis
python -m pytest tests -q
python -m pytest tests -q --cov=src --cov-report=term-missing --cov-fail-under=85
# services/ and security/ must both read 100 %

# 4. migration diff — NEVER straight after pytest (see PHASE-03 §1.3).
#    The _schema fixture drops every table on teardown while alembic_version
#    survives claiming head, so autogenerate then "detects" the whole schema as
#    new. That is the fixture talking, not a real diff.
alembic stamp base
alembic upgrade head
alembic revision --autogenerate -m "probe"
#    Open the generated file: upgrade() must be `pass`. Then delete it:
Remove-Item alembic\versions\*probe.py

# 5. grep gates
Select-String -Path src\*.py -Recurse -Pattern "HTTPException"
Select-String -Path src\*.py -Recurse -Pattern "passlib"
Select-String -Path src\*.py -Recurse -Pattern "jwt\." |
    Where-Object { $_.Path -notmatch "jwt_manager" }
#    All three must print nothing. (Verified empty on this branch.)

# 6. Swagger
#    Start the app, open /docs, click Authorize, paste an access token from
#    POST /accounts/login/, then call POST /accounts/logout/ and confirm it is
#    reached rather than 401.
```

## Merge

```powershell
git checkout main
git merge --no-ff phase-03-jwt-authentication
git push origin main
git branch -d phase-03-jwt-authentication
```
