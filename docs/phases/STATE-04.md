# STATE-04 — Password Management & Role-Based Access Control

> **Gate status: green except the migration diff and Swagger.**
>
> | Gate | Result |
> |---|---|
> | `ruff check src tests` | passed |
> | `black --check src tests` | 90 files unchanged |
> | `mypy --strict src/` | passed — after the ignore-code fix below |
> | `pytest tests` | **269 passed** |
> | coverage | **94.45 %** overall; `security/` 100 %, `services/` 100 % on everything this phase touched |
> | grep gates (4) | clean; the role gate returns its three expected hits |
> | Alembic autogenerate diff | **not run** — expected empty, no model changed |
> | Swagger walk-through | **not run** |
>
> Two service modules sit at 97 % and predate this phase:
> `activation.py:83` (activation submitted for an address with no account) and
> `registration.py:75` (the default group missing). Both are unreachable from the
> endpoints as currently tested; if the 100 %-on-`services/` rule is to be enforced
> literally, they want the same treatment `AdminService`'s unseeded-group branch
> got in `tests/integration/test_admin_service.py`.

## Modules created

```
src/security/permissions.py
    Permission(StrEnum)          BROWSE_CATALOG, RATE_AND_COMMENT,
                                 PURCHASE_TICKETS, MANAGE_MOVIES,
                                 MODERATE_COMMENTS, VIEW_SALES, MANAGE_USERS
    GROUP_PERMISSIONS: Mapping[UserGroupEnum, frozenset[Permission]]
                                 MappingProxyType; each row built as a union of
                                 the row below it
    has_permission(group, permission) -> bool        # hierarchical
    belongs_to_any(group, allowed) -> bool           # exact membership

src/schemas/password.py
    _NewPasswordSchema           new_password: str (8..128) + strength rules
    PasswordChangeRequestSchema  old_password (min_length=1), new_password
    PasswordResetRequestSchema   email
    PasswordResetCompleteSchema  email, token, new_password
    All set extra="forbid"; only the replacement password is strength-checked.

src/schemas/admin.py
    GroupChangeRequestSchema     group: UserGroupEnum
    UserAdminResponseSchema      id, email, is_active, group

src/services/accounts/password.py
    INVALID_OLD_PASSWORD_MESSAGE, PASSWORD_UNCHANGED_MESSAGE,
    INVALID_RESET_TOKEN_MESSAGE
    PasswordService(users, reset_tokens, refresh_tokens, email_sender,
                    reset_ttl, reset_url)
        async change_password(user: User, old_password, new_password) -> None
        async request_reset(email) -> None
        async complete_reset(email, token, new_password) -> None

src/services/accounts/admin.py
    UNKNOWN_ACCOUNT_MESSAGE, ACCOUNT_ALREADY_ACTIVE_MESSAGE,
    MISSING_GROUP_MESSAGE
    AdminService(users, groups, activation_tokens)
        async change_group(user_id, group: UserGroupEnum) -> User
        async activate_manually(user_id) -> User

src/api/providers.py
    get_registration_service / get_activation_service /
    get_authentication_service / get_password_service / get_admin_service
    and their *Dep aliases.  Moved out of deps.py — see decision 6.

src/api/v1/admin.py
    router = APIRouter(prefix="/admin", tags=["admin"],
                       dependencies=[ADMIN_ONLY])
    _as_admin_view(user) -> UserAdminResponseSchema
    PATCH /admin/users/{user_id}/group/     200 UserAdminResponseSchema
    POST  /admin/users/{user_id}/activate/  200 UserAdminResponseSchema

src/integrations/email/templates/password_reset.html
src/integrations/email/templates/password_changed.html
```

## Modules changed

```
src/api/deps.py               Service assembly removed (now providers.py).
                              require_group(*groups) -> Callable[[User], User]
                              require_permission(permission) -> same
                              ADMIN_ONLY = Depends(require_group(ADMIN))
                              INSUFFICIENT_GROUP_MESSAGE,
                              MISSING_PERMISSION_MESSAGE
                              get_current_user now loads via get_with_group
                              222 lines, down from 335 before the split.
src/repositories/accounts.py  UserRepository.get_with_group(user_id)
                              selectinload(User.group) + populate_existing
src/services/accounts/links.py
                              _credentialed_link shared by
                              build_activation_link and
                              build_password_reset_link
src/core/config.py            Settings.password_reset_url property
.env.sample                   FRONTEND_BASE_URL comment mentions reset links
                              (no new variable: PASSWORD_RESET_TTL_MINUTES has
                              existed since phase 0 and is now consumed)
src/integrations/email/interface.py
                              + send_password_reset_email(email, reset_link)
                              + send_password_changed_email(email)
src/integrations/email/smtp_sender.py
                              PASSWORD_RESET_SUBJECT,
                              PASSWORD_CHANGED_SUBJECT + both methods
src/api/v1/accounts.py        PASSWORD_CHANGED_MESSAGE,
                              RESET_ACKNOWLEDGED_MESSAGE,
                              RESET_COMPLETE_MESSAGE
                              POST /accounts/change-password/           200
                              POST /accounts/password-reset/request/    200
                              POST /accounts/password-reset/complete/   200
src/api/v1/router.py          admin router included
src/tasks/tokens.py           _purge_expired(model: type[TokenT]) generic body
                              purge_expired_password_reset_tokens
src/tasks/celery_app.py       beat entry purge-expired-password-reset-tokens
                              at crontab(minute=30)
tests/doubles/fake_email.py   both new methods + their subjects
tests/e2e/conftest.py         the autouse fixture seeds *every* group through
                              ensure_default_groups (see decision 8)
tests/e2e/accounts_support.py access_token_for(user)
```

## HTTP contract added

| Route | Method | Auth | Success | Failures |
|---|---|---|---|---|
| `/api/v1/accounts/change-password/` | POST | Bearer | 200 | 400 same password · 401 no/bad token or wrong current password · 403 inactive · 422 weak or malformed |
| `/api/v1/accounts/password-reset/request/` | POST | public | 200 neutral | 422 malformed · 502 mail |
| `/api/v1/accounts/password-reset/complete/` | POST | public | 200 | 400 invalid/spent/expired/foreign token · 422 weak · 502 mail |
| `/api/v1/admin/users/{id}/group/` | PATCH | Bearer + ADMIN | 200 | 401 · 403 · 404 unknown user or unseeded group · 422 unknown group |
| `/api/v1/admin/users/{id}/activate/` | POST | Bearer + ADMIN | 200 | 400 already active · 401 · 403 · 404 |

## Test modules

| File | Covers |
|---|---|
| `tests/e2e/test_password_change.py` | `TestPasswordChange` — credential swap, session revocation, 401 on a wrong current password, 400 on reuse, six strength rules, anonymous, and that no payload can name another account |
| `tests/e2e/test_password_reset.py` | `TestResetRequest`, `TestResetCompletion` — neutral request, supersession, byte-identical answers, completion, expiry as 400, foreign and replayed tokens, inactive accounts, six strength rules |
| `tests/e2e/test_permissions.py` | the group table over every guarded route, 401-not-403 for anonymous callers, and `require_permission` through a test-only `/probe/sales/` |
| `tests/e2e/test_admin_users.py` | `TestGroupChange`, `TestManualActivation` — including the change applying to the very next request |
| `tests/integration/test_admin_service.py` | the unseeded-group branch, which no request can reach once the groups exist |
| `tests/unit/test_permission_matrix.py` | the matrix is total, immutable, strictly hierarchical, and `MANAGE_USERS` is admin-only |
| `tests/unit/test_email_sender_contract.py` | the double and the SMTP sender implement every interface method with identical signatures |
| `tests/unit/test_password_reset_purge.py` | the beat entry, the task registration, and the sweep itself |
| `tests/e2e/passwords_support.py`, `tests/e2e/rbac_support.py` | shared URLs, payload builders and account builders |

## Migration

**None.** No model, column, constraint or enum changed in this phase —
`git diff main -- src/models src/db` is empty apart from the seeding call site.
`PasswordResetToken` has existed since phase 1. Confirm the autogenerate diff is
empty per the runbook, and never straight after pytest.

## Decisions affecting later phases

1. **An expired reset link answers 400, not 401.** `TokenExpiredError` keeps its
   global mapping and this module lets it travel. A refresh token is a credential,
   so the session endpoints translate the same error to 401; a reset link is a
   well-formed submission the current state forbids, exactly like a stale
   activation link. Do not "fix" this by copying the authentication service.
   *This resolves the open question in STATE-03 decision 2.*
2. **Replacing a credential revokes every refresh row.** Both `change_password`
   and `complete_reset` call `revoke_for(user_id)`. This is the log-out-everywhere
   caller STATE-03 decision 5 anticipated; it is the one place that wants
   `issue()`'s default `replace_existing=True` semantics rather than the login
   path's `False`.
3. **A new reset request kills the previous link.** Plain default behaviour of
   `TokenLifecycleService.issue`; no flag was added and none should be.
4. **A group change applies to the target's next request, not their next login.**
   `get_current_user` reloads the account through
   `UserRepository.get_with_group`, which combines `selectinload(User.group)` with
   `populate_existing=True`. Anything in a later phase that reads a role must use
   that lookup: `get_by_id` returns an identity-mapped instance with a lazy
   relationship, and touching `user.group` on it raises under the async driver.
   This is also why neither admin operation revokes a session — there is no stale
   authority to revoke. *The ROADMAP's "effective on the next login" is weaker
   than what is implemented and tested.*
5. **`require_group` is exact; `require_permission` is hierarchical.**
   `require_group(MODERATOR)` does not admit an administrator. A route whose
   audience should widen with rank asks for a permission. Both guards compose with
   `CurrentUserDep` and return the account, so one parameter can gate a route and
   supply the caller. **New guarded routes belong in the table at the top of
   `tests/e2e/test_permissions.py`** — one row, not a new test function.
6. **`api/deps.py` no longer builds services.** With the two guards added it stood
   at 335 lines against the project's 300-line ceiling, so service assembly moved
   to `api/providers.py`. The seam: `deps.py` answers *who is calling* and hands
   out infrastructure, `providers.py` turns infrastructure into services. A phase-5
   service provider goes in `providers.py`; a new guard goes in `deps.py`. This
   deviates from PHASE-04 §3, which put both in one file.
7. **Role names appear in exactly two modules.** `src/security/permissions.py`
   (the matrix) and `src/api/deps.py` (the `ADMIN_ONLY` factory argument). Routers
   receive a guard, never a group. `src/schemas/admin.py` writes its OpenAPI
   example group as the literal `"moderator"` for this reason — the field is typed
   as the enum, so nothing is lost, and the grep gate cannot tell an example from
   a comparison.
8. **The e2e autouse fixture now seeds every group**, through the production
   `ensure_default_groups`, because an administrator may move an account into any
   of them and `ASGITransport` does not run the lifespan hook. A test that wants a
   specific group still calls `create_group`, which is get-or-create.
9. **Password mail goes out inside the request.** As with activation, a transport
   failure raises `ExternalServiceError`, the session dependency rolls back, and
   the account keeps the credential its owner still believes in. The cost is that
   an SMTP outage turns a change into a 502.
10. **Wrong current password is 401, not the 400 the ROADMAP predicted.** It is a
    credential comparison, and the project answers a failed credential with 401
    everywhere else. PHASE-04 §4 agrees; the ROADMAP line is stale.

## Known technical debt

- **`untyped-decorator` is the right ignore code on the Celery tasks**, as phase 3
  had it. This phase briefly changed both to `[misc]` on the assumption that the
  former was not a real mypy code; it is, and the first `mypy --strict` run on
  this repository said so twice over (unused ignore *and* uncovered error code).
  Reverted. Do not "correct" it again.
- **The Alembic diff and the Swagger walk-through are still unrun.** The diff is
  expected to be empty — `git diff main -- src/models src/db` shows no model
  change — but expected is not verified.
- **The guards are synchronous dependencies**, so FastAPI runs them in a
  threadpool. That is safe only because `get_current_user` eager-loads the group:
  a guard that ever reads a lazily-loaded attribute would attempt IO from a worker
  thread and raise `MissingGreenlet`. If a guard needs to touch anything else on
  the account, make it `async def` first.
- **Four of the seven permissions have no route yet** (`BROWSE_CATALOG`,
  `RATE_AND_COMMENT`, `PURCHASE_TICKETS`, `MODERATE_COMMENTS`). They exist so that
  phase 5 adds rows to the matrix rather than inventing the vocabulary under
  deadline. Only `VIEW_SALES` and `MANAGE_USERS` are exercised, the former through
  a test-only probe route since no production endpoint uses
  `require_permission` yet.
- **`change_password` performs three bcrypt operations** — verify the old
  password, verify the new one against the stored hash to reject a no-op change,
  then hash the replacement. At twelve rounds that is roughly three quarters of a
  second per call, which is fine for the endpoint and noticeable in the suite.
- **`tests/unit/test_password_reset_purge.py` touches the database** although it
  lives under `tests/unit/`; the path comes from PHASE-04 §4 and the module
  carries the `integration` marker. Move it if that inconsistency ever grates.
- **The moderator and plain-user 403 cases for the admin routes live only in the
  RBAC table**, deliberately not duplicated in `test_admin_users.py`.
- **`black` was verified with 26.5.1**, not the `^24.10` the project pins. It
  agreed with every pre-existing file, so the risk is small, but re-run the pinned
  version locally before trusting the gate.
- Still open from phase 0, deliberately untouched: permissive CORS, unused
  `aiosqlite`, no healthcheck on `celery-worker` / `celery-beat`.

## Note for phase 5

Nothing here pushed toward `core/pagination.py` or `core/filtering.py`; no list
endpoint was added, and the only generic helper this phase produced is the
credentialed-link builder, which is shared rather than duplicated. The growth
point phase 5 inherits is the authorisation table in
`tests/e2e/test_permissions.py` and the matrix rows for the movie permissions
that already exist by name.

## Git

```
Branch: phase-04-passwords-rbac
Commits: 17 (2 docs, 5 test-first, 8 feat, 1 refactor, 1 style)
Merged to main as <hash> (--no-ff), branch deleted   <- fill in after the gates pass
```

```
docs(phase-04): add the password and RBAC phase brief
test(accounts): add failing tests for password change and reset
test(security): add failing tests for the permission matrix
test(admin): add failing tests for group change and manual activation
test(tasks): add failing tests for the reset purge and mail contract
test(accounts): cover the reset paths a seeded database cannot reach
feat(schemas): add password and admin schemas
feat(security): add the group to permission matrix
feat(integrations): extend the e-mail interface with password notifications
refactor(repositories): add a group-loading user lookup
feat(accounts): implement password change and reset services
feat(admin): implement group change and manual activation
feat(api): add require_group and require_permission dependencies
feat(api): expose password and admin endpoints
feat(tasks): purge expired password reset tokens
style(tests): format the new test modules with black
docs(phase-04): record handoff state and the remaining gate runbook
```

## Runbook — gates still to run

PowerShell, from the repository root, virtualenv active. Everything STATE-03 said
still applies: pass `tests` explicitly, and never run the Alembic diff straight
after pytest.

```powershell
# 1. static — green as of this branch (ruff 0.8 rules E,F,I,B,UP,SIM,C4,ANN)
ruff check src tests
black --check src tests

# 2. types — needs Python 3.12
mypy --strict src/

# 3. tests — needs the compose stack up
docker compose up -d db redis
python -m pytest tests -q
python -m pytest tests -q --cov=src --cov-report=term-missing --cov-fail-under=85
#    services/ and security/ must both read 100 %. If services/ falls short, the
#    likely culprits are AdminService's unseeded-group branch (covered only by
#    tests/integration/test_admin_service.py) and PasswordService's
#    _resettable_account guard (covered only by the two completion cases added in
#    the last test commit).

# 4. migration diff — expected empty; no model changed this phase
alembic stamp base
alembic upgrade head
alembic revision --autogenerate -m "probe"
#    upgrade() must be `pass`, then:
Remove-Item alembic\versions\*probe.py

# 5. grep gates — all four must print nothing except where noted
Select-String -Path src\*.py -Recurse -Pattern "HTTPException"
Select-String -Path src\*.py -Recurse -Pattern "passlib"
Select-String -Path src\*.py -Recurse -Pattern "jwt\." |
    Where-Object { $_.Path -notmatch "jwt_manager" }
#    New gate: role comparisons. Exactly three hits are expected —
#    two matrix rows in permissions.py and the ADMIN_ONLY argument in deps.py.
Select-String -Path src\*.py -Recurse -Pattern "UserGroupEnum\.(ADMIN|MODERATOR)|group\.name =="

# 6. Swagger
#    /docs must show the five new endpoints. Authorize with an access token from
#    POST /accounts/login/, then confirm:
#      - POST /accounts/change-password/ is reached rather than 401
#      - the two /admin routes answer 403 for a plain user and 200 for an
#        administrator (promote one with a direct UPDATE, or seed one by hand)
```

## Merge

```powershell
git checkout main
git merge --no-ff phase-04-passwords-rbac
git push origin main
git branch -d phase-04-passwords-rbac
git push origin --delete phase-04-passwords-rbac
```
