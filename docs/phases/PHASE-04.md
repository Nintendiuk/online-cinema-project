# PHASE 04 — Password Management & Role-Based Access Control

**How to use this document:** paste `STATE-03` first, then this file, into a fresh Claude Pro chat. Claude implements the whole phase itself — conventions come from `CLAUDE.md` and `docs/ARCHITECTURE.md` in the repository. No task cards, no external models.

---

## 1. Scope

Four capabilities, one branch:

1. **Change password** — authenticated, requires the old password.
2. **Reset password** — emailed token, no old password needed.
3. **RBAC** — a declarative group → permission matrix and a single dependency that enforces it.
4. **Admin operations** — change a user's group, activate an account manually.

Out of scope: user listing (needs pagination from phase 5), profile editing, avatar upload.

---

## 2. Decisions to make deliberately

These are the places where this phase can quietly contradict phases 2–3.

**2.1 Expiry status code.** `TokenExpiredError` maps globally to 400. Phase 3 chose to translate it to `AuthenticationError` (401) on the authentication paths, because there it means a credential. A stale password-reset link is **not** a credential — it is a well-formed request the current state forbids. Keep it at **400**, matching the activation link. Record the reasoning; do not let it drift to 401 by copying the auth service.

**2.2 Changing a password must end every session.** Call `revoke_for(user_id)` on the refresh-token lifecycle after both a successful change and a successful reset. This is the "log out everywhere" caller that `STATE-03` decision 5 anticipated — it wants `issue()`'s default `replace_existing=True` semantics, not the login path's.

**2.3 A new reset request invalidates the previous one.** That is the default `replace_existing=True` behaviour of `TokenLifecycleService`. Do not add a flag; just do not pass `False`.

**2.4 Group changes take effect on the next request, not the next login.** `get_current_user` reloads the user from the database on every call, so the access token carries no stale role. Assert this with a test rather than leaving it implicit — it is the reason no session invalidation is needed on a group change.

**2.5 `require_group` builds on `CurrentUserDep`.** Per `STATE-03` decision 1 that is the only authentication dependency. The permission check composes with it; it does not re-decode the token.

**2.6 No account enumeration on reset request.** Active, inactive, and unknown emails all return the same status and the same body. Only the active case sends mail.

---

## 3. Build list

**`src/security/permissions.py`**
A `Permission` StrEnum (`MANAGE_MOVIES`, `VIEW_SALES`, `MANAGE_USERS`, …) and a `GROUP_PERMISSIONS: Mapping[UserGroupEnum, frozenset[Permission]]` matrix where `ADMIN` is a superset of `MODERATOR`, which is a superset of `USER`. One `has_permission(group, permission) -> bool` helper. This module is the only place a role is compared to anything.

**`src/api/deps.py`**
`require_group(*groups: UserGroupEnum)` and `require_permission(permission: Permission)` — dependency factories returning a callable that depends on `CurrentUserDep` and raises `PermissionDeniedError`. Plus `get_password_service`, `get_admin_service` and their `*Dep` aliases.

**`src/schemas/password.py`**
`PasswordChangeRequestSchema` (old, new), `PasswordResetRequestSchema` (email), `PasswordResetCompleteSchema` (email, token, new password). Strength validation on the new password only, via the existing `validate_password_strength`. `extra="forbid"` throughout.

**`src/schemas/admin.py`**
`GroupChangeRequestSchema` (`group: UserGroupEnum`), `UserAdminResponseSchema` (id, email, is_active, group).

**`src/services/accounts/password.py`**
`PasswordService(users, reset_tokens, refresh_tokens, email_sender, reset_ttl, reset_url)`:
- `change_password(user, old, new)` — verify old → `AuthenticationError`; reject new identical to old → `InvalidRequestError`; validate strength before hashing; revoke all refresh tokens
- `request_reset(email)` — neutral response, mail only for active accounts
- `complete_reset(email, token, new_password)` — consume the token, set the hash, revoke all refresh tokens

**`src/services/accounts/admin.py`**
`AdminService(users, groups, activation_tokens)`:
- `change_group(user_id, group)` — 404 for an unknown user; changing to the current group is a no-op, not an error
- `activate_manually(user_id)` — sets `is_active`, deletes any pending activation token; already-active raises `InvalidRequestError`

**Email**
Extend `EmailSenderInterface` with `send_password_reset_email(email, reset_link)` and `send_password_changed_email(email)`. Update `SMTPEmailSender` and `FakeEmailSender` together — the double must never drift from the interface. Add `password_reset.html` and `password_changed.html` alongside the existing templates, same 600 px inline-CSS style.

**`src/api/v1/accounts.py`** — append:
```
POST /accounts/change-password/            200, Bearer required
POST /accounts/password-reset/request/     200, public, neutral
POST /accounts/password-reset/complete/    200, public
```

**`src/api/v1/admin.py`** — new router, prefix `/admin`, every route behind `require_group(ADMIN)`:
```
PATCH /admin/users/{user_id}/group/        200 UserAdminResponseSchema
POST  /admin/users/{user_id}/activate/     200 UserAdminResponseSchema
```

**`src/tasks/tokens.py`**
`purge_expired_password_reset_tokens` — same thin-wrapper shape as the activation purge, delegating to `purge_expired`. Add the beat entry.

---

## 4. Test scenarios

Write these before the implementation, in a separate failing commit.

**Change password** (`tests/e2e/test_password_change.py`)
- correct old password → 200; old password no longer authenticates; new one does
- **every refresh token for that user is gone**; a refresh issued before the change → 401
- wrong old password → 401
- new identical to old → 400
- new failing strength → 422, parametrized over the six rules including the 72-byte bcrypt limit
- unauthenticated → 401
- user A cannot change user B's password (no user id in the payload — the route takes it from the token)

**Reset flow** (`tests/e2e/test_password_reset.py`)
- request for an active email → 200, one mail sent, one token row
- a second request replaces the first; the first token then fails → 400
- request for an inactive account and for an unknown email → 200 with a body **byte-identical** to the active case, no mail sent
- complete with a valid token → 200; password changed; token row deleted; **all refresh tokens revoked**
- expired token → **400** (per §2.1), and the message names expiry
- token belonging to another user → 400
- reused token → 400
- weak new password → 422

**RBAC** (`tests/e2e/test_permissions.py`)
- one parametrized table over `(endpoint, method, group, expected_status)` covering USER / MODERATOR / ADMIN against every guarded route that exists so far. One test function, not one per endpoint — this table grows every phase.
- unauthenticated against a guarded route → 401, not 403
- `has_permission` unit tests: the matrix is genuinely hierarchical (every MODERATOR permission is in ADMIN, every USER permission is in MODERATOR)

**Admin** (`tests/e2e/test_admin_users.py`)
- admin changes a user's group → 200; **the change is effective on the very next request with the same access token** (§2.4)
- admin activates an inactive user → 200; `is_active` true; pending activation token deleted
- activating an already-active user → 400
- unknown user id → 404
- moderator attempting either → 403
- regular user attempting either → 403

**Task** (`tests/unit/test_password_reset_purge.py`)
- deletes only expired rows, leaves valid ones, safe on an empty table

---

## 5. Acceptance gates

- [ ] `pytest tests` green; coverage `src/services/` and `src/security/` = 100 %, overall ≥ 85 %
- [ ] `mypy --strict src/` clean; `ruff` + `black --check` clean
- [ ] `grep`-equivalent gates still empty: `HTTPException`, `passlib`, `jwt.` outside `jwt_manager.py`
- [ ] **new gate:** no role comparison outside `src/security/permissions.py` — searching `src/` for `UserGroupEnum.ADMIN`, `.MODERATOR`, `group.name ==` returns hits only in that module and in `deps.py`'s factory arguments
- [ ] one `TokenLifecycleService`, still not forked
- [ ] `FakeEmailSender` implements every `EmailSenderInterface` method — a test asserts the double has no missing overrides
- [ ] Alembic autogenerate diff empty (`alembic stamp base && alembic upgrade head` first, never straight after pytest)
- [ ] no module over 300 lines
- [ ] Swagger shows the five new endpoints with auth requirements and documented error codes

---

## 6. Git

```
git checkout main
git pull
git checkout -b phase-04-passwords-rbac
```

Tests commit first, failing, separate from the implementation. Suggested order:

```
test(accounts): add failing tests for password change and reset
test(security): add failing tests for the permission matrix
test(admin): add failing tests for group change and manual activation
feat(schemas): add password and admin schemas
feat(security): add group to permission matrix
feat(api): add require_group and require_permission dependencies
feat(integrations): extend email interface with password notifications
feat(accounts): implement password change and reset services
feat(admin): implement group change and manual activation
feat(api): expose password and admin endpoints
feat(tasks): purge expired password reset tokens
```

Merge and clean up:

```
git checkout main
git merge --no-ff phase-04-passwords-rbac
git push origin main
git branch -d phase-04-passwords-rbac
git push origin --delete phase-04-passwords-rbac
```

Commit messages: `<type>(<scope>): <imperative summary>`, ≤ 72 chars, no trailing period, body explaining **why** when the change is not self-evident. `wip` / `fixes` / `update code` are rejected.

---

## 7. Hand-off

Emit `STATE-04` in the same shape as `STATE-03`: modules created, modules changed, decisions affecting later phases, known technical debt, git block, and any runbook notes that would otherwise be rediscovered the hard way.

Phase 5 (movie catalog) is the first phase that needs `core/pagination.py` and `core/filtering.py`. If anything in this phase pushes toward a generic list-and-filter helper, note it in `STATE-04` rather than building it here.
