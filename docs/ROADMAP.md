# Online Cinema — Phase Roadmap (TDD-enforced)

**Non-negotiable rule for every phase: Step A (tests) is committed and failing before any Step B code is written.** A phase is complete only when Step C gates pass in CI.

Branch per phase: `phase-<n>-<slug>` (e.g. `phase-02-registration-activation`). Commits: `<type>(<scope>): <imperative summary>` — `feat(accounts): issue activation token on registration`.

---

## Feature Selection (satisfies the "6–8 custom features" requirement)

Deliver these eight, in order. Everything else in the brief is supporting infrastructure.

1. Registration with email activation + expiring/resendable tokens (celery-beat purge)
2. JWT authentication: login, refresh, logout with revocation
3. Password management: change with old password, reset by emailed token, complexity enforcement
4. Role-based access control: User / Moderator / Admin, admin group management and manual activation
5. Movie catalog: pagination, filtering, sorting, full-text-style search across title/description/star/director
6. Engagement: likes, 10-point ratings, comments with replies, favorites, reply/like notifications
7. Shopping cart with purchase-state validation
8. Orders + Stripe payments with webhook validation, email confirmation, and refund status handling

---

## Phase 0 — Foundation & Test Harness

**Step A (Test Phase) — write first**
- `tests/unit/test_config.py`: settings load from env; missing required var raises; `.env.sample` covers every field.
- `tests/integration/test_db_connection.py`: engine connects, session yields, rollback isolates between tests.
- `tests/e2e/test_health.py`: `GET /health` → 200 `{"status": "ok"}`.
- Failure modes to assert: unset `DATABASE_URL` fails fast at import; two tests writing the same unique row both pass (proves rollback isolation).

**Step B (Implementation Phase)**
- Poetry project; dependency groups `main` / `dev`. Pin Python 3.12.
- `core/config.py`: single `Settings(BaseSettings)`, cached accessor. No `os.getenv` anywhere else in the codebase.
- `db/base.py`: `DeclarativeBase` with naming convention for constraints (required for clean Alembic autogenerate); `IntPKMixin`, `TimestampMixin`, `TokenMixin`.
- `db/session.py`: async engine + sessionmaker + `get_session` dependency owning commit/rollback.
- `core/exceptions.py` hierarchy + handler registration in `main.py`. `main.py` contains `create_app()` only.
- `tests/conftest.py`: session-scoped engine, function-scoped nested transaction rollback, `AsyncClient` with dependency overrides.
- Alembic initialised against the async engine.
- Docker Compose: `web`, `db` (Postgres), `redis`, `celery`, `celery-beat`, `minio`, `mailhog`. One `docker compose up` starts everything.

**Step C (Verification Phase)**
- `ruff`, `black --check`, `mypy --strict src/` all clean.
- CI workflow runs lint → types → tests → coverage and is green on the branch.
- `docker compose up` reaches healthy state from a clean clone; README documents the command.

---

## Phase 1 — Accounts Data Layer

**Step A**
- Unit: `UserGroupEnum` / `GenderEnum` membership and value stability.
- Integration: create user requires existing group; duplicate email raises `IntegrityError`; `email` stored lowercase/trimmed; `hashed_password` never equals the plaintext; profile `user_id` unique (second profile for same user fails); cascade delete of user removes profile and all tokens; token `expires_at` is timezone-aware.
- Boundary: email at max length; empty-string email rejected; `is_active` defaults to `False`.

**Step B**
- `models/accounts.py`: `UserGroup`, `User`, `UserProfile`, `ActivationToken`, `PasswordResetToken`, `RefreshToken` exactly per the entity spec (unique `user_id` on activation/reset/profile; `refresh_tokens.user_id` non-unique).
- All three token models inherit `TokenMixin` — no duplicated columns.
- `security/passwords.py` hash/verify; `security/validators.py` password complexity + email normalisation.
- `db/seed/groups.py`: idempotent insert of the three groups; wired into startup or a CLI command.
- Alembic migration + verified `downgrade`.

**Step C**
- Migration applied to an empty DB reproduces the model metadata (autogenerate diff is empty).
- `mypy --strict` clean on `models/` and `security/`.
- Coverage 100 % on `security/`.

---

## Phase 2 — Registration & Account Activation

**Step A**
- E2E: `POST /accounts/register` → 201, user inactive, activation token persisted, exactly one email dispatched to the fake sender.
- Conflict: registering an existing email → 409, no second user row, no email sent.
- Validation: weak password → 422 with field-level detail; malformed email → 422.
- Activation: valid token → 200 and `is_active=True`, token deleted; reused token → 400; token past `expires_at` → 400 with an expiry-specific message; token belonging to another user → 400.
- Resend: `POST /accounts/resend-activation` for an expired token issues a fresh 24 h token and invalidates the previous one; for an already-active account returns a neutral response and sends nothing; unknown email returns the same neutral response (no user enumeration).
- Celery task unit test: `purge_expired_activation_tokens` deletes only rows with `expires_at < now`, leaves valid ones, and is safe to run on an empty table.

**Step B**
- `services/accounts/registration.py`, `services/accounts/activation.py`.
- Generic token-lifecycle helper parameterised by model — reused later by password reset and refresh. Do not fork it.
- `integrations/email/interface.py` + SMTP implementation + templates; services depend on the ABC only.
- `tasks/celery_app.py` with `beat_schedule` entry for the purge task; task delegates to the same service used in tests.
- Routes in `api/v1/accounts.py` — thin, one service call each.

**Step C**
- Coverage 100 % on `services/accounts/`.
- No `HTTPException` raised outside the exception handler.
- Swagger shows request/response models and every documented error code for the three endpoints.

---

## Phase 3 — JWT Authentication

**Step A**
- Unit: access/refresh encode-decode round trip; tampered signature rejected; expired token rejected; wrong-type token (refresh used as access) rejected; access TTL strictly shorter than refresh TTL.
- E2E: login with valid credentials → 200 with both tokens; wrong password → 401; **inactive account → 403 with an activation-required message**; unknown email → 401 with the same body as wrong password (no enumeration).
- Refresh: valid refresh → new access token; refresh token not in DB → 401; expired refresh → 401.
- Logout: revokes the refresh token; subsequent refresh with it → 401; logout without auth → 401.
- Protected-route probe: no header → 401; malformed `Authorization` header → 401.

**Step B**
- `security/jwt_manager.py`: `JWTAuthManagerInterface` + implementation, injected via `api/deps.py`.
- `services/accounts/authentication.py`: login, refresh, logout. Refresh tokens persisted and deleted on logout.
- `api/deps.py`: `get_current_user` — the single auth dependency for the whole project.

**Step C**
- No secret keys or TTLs hardcoded outside `Settings`.
- `mypy --strict` clean; coverage 100 % on `security/jwt_manager.py`.

---

## Phase 4 — Password Management & RBAC

**Step A**
- Change password: correct old password → 200 and old password no longer authenticates; wrong old password → 400; new password identical to old → 400; new password failing complexity → 422; unauthenticated → 401.
- Reset flow: request for active email issues a token and sends one email; request for inactive or unknown email returns the identical neutral response; a second request invalidates the first token; complete-reset with valid token sets the password and deletes the token; expired token → 400.
- RBAC: parametrised matrix test — for each protected endpoint assert allowed/forbidden per group (User / Moderator / Admin). Table-driven, one test function, not one test per endpoint.
- Admin: change a user's group → 200 and the change is effective on the next login; manually activate an inactive user → 200 and pending activation tokens are cleared; a Moderator attempting either → 403.

**Step B**
- `services/accounts/password.py`, `services/accounts/admin.py`.
- `security/permissions.py`: declarative group → permission matrix; `api/deps.py::require_group(...)` factory is the only enforcement mechanism.
- Reuse the Phase 2 token-lifecycle helper for reset tokens.

**Step C**
- Grep audit: zero inline role comparisons (`user.group.name ==`) outside `security/permissions.py`.
- Coverage 100 % on `services/accounts/`.

---

## Phase 5 — Movies Domain & Moderator CRUD

**Step A**
- Integration: unique `(name, year, time)` composite constraint violated → error; `certification_id` is required; `price` persists as `Decimal` with 2 dp; `uuid` unique and auto-generated; many-to-many links to genres/stars/directors created and removed cleanly; deleting a movie removes association rows but not the genres/stars themselves.
- E2E moderator CRUD: create → 201 with nested genres/stars/directors resolved-or-created; create duplicate → 409; update partial → 200; delete → 204.
- **Delete guards:** movie present in any `OrderItem` of a paid order → 409 with a purchased-movie message; movie present in any user's cart → 409 (or 200 with an explicit moderator warning payload — pick one and test it).
- Permissions: regular User calling any write endpoint → 403.
- Boundary: `year` below/above plausible bounds → 422; negative `price` → 422; `imdb` outside 0–10 → 422; empty `name` → 422.

**Step B**
- `models/movies.py`: `Genre`, `Star`, `Director`, `Certification`, `Movie` + association tables `movie_genres (movie_id, genre_id)`, `movie_directors (movie_id, director_id)`, `movie_stars (movie_id, star_id)` — each with a composite primary key, exactly per spec.
- `repositories/movies.py` on top of `BaseRepository`; a shared get-or-create helper for genre/star/director resolution used by create **and** update.
- `services/movies/management.py` holds the delete guards; routers stay thin.
- `validation/movies.py` field validators shared by create and update schemas.
- CSV catalog import command in `commands/`.

**Step C**
- Alembic autogenerate diff empty after migration.
- No duplicated get-or-create logic between create and update paths.
- Coverage ≥ 90 % on `services/movies/`.

---

## Phase 6 — Catalog Read API: Pagination, Filtering, Sorting, Search

**Step A**
- Pagination: default page size; `page=0` and `page_size=0` → 422; page beyond the last → 200 with an empty list and correct `total`; `total` matches the unfiltered-by-page count; prev/next links correct on first and last page.
- Filtering: by year, year range, IMDb minimum, price range, genre, certification; combined filters compose with AND; unknown filter value → empty result, not an error; invalid type → 422.
- Sorting: by price, release year, and popularity, both directions; unknown sort field → 422; sort is stable (secondary key on `id`).
- Search: matches title, description, star name, and director name; case-insensitive; partial match; no match → empty page.
- Genres list: returns each genre with an accurate movie count including zero-count genres; genre detail returns only that genre's movies and honours the same pagination/filter/sort params.
- Performance guard: listing N movies issues a bounded number of queries (assert no N+1 via query counting).

**Step B**
- `core/pagination.py` and `core/filtering.py` — generic, reused verbatim by favorites in Phase 7.
- `services/movies/catalog.py` read use cases; repository builds queries with eager loading (`selectinload`) to satisfy the N+1 guard.
- Distinct list vs detail response schemas.

**Step C**
- Filter/sort logic exists in exactly one module; routers pass a params object, nothing more.
- `mypy --strict` clean on generics.

---

## Phase 7 — Engagement: Likes, Ratings, Comments, Favorites, Notifications

**Step A**
- Likes: like → 201; repeat like is idempotent or toggles (choose and test); dislike replaces like; unlike removes the row; counts on movie detail are accurate.
- Ratings: 1–10 accepted; 0 and 11 → 422; non-integer → 422; re-rating updates rather than duplicates; average rating recomputed correctly.
- Comments: create → 201; reply nests under parent; reply to a non-existent parent → 404; empty body → 422; author and timestamp present; comments paginated.
- Notifications: replying to a comment notifies the parent author exactly once; liking a comment notifies its author; self-reply and self-like notify nobody.
- Favorites: add → 201; duplicate add → 409; remove → 204; favorites list supports the *same* search/filter/sort/pagination params as the catalog (assert with a shared parametrised test body).
- Unauthenticated access to every write endpoint → 401.

**Step B**
- `models/movies.py` additions: `MovieLike`, `MovieRating`, `MovieComment` (self-referencing `parent_id`), `CommentLike`, `Favorite`, each with the appropriate unique constraint on `(user_id, target_id)`.
- `services/movies/interactions.py`; notification dispatch through the existing `EmailSenderInterface` — no second notification mechanism.
- Favorites service composes the Phase 6 filter/pagination primitives; zero new filtering code.

**Step C**
- Test asserting the favorites and catalog query paths share the filter builder (import-level or behavioural equivalence test).
- Coverage ≥ 90 % on interactions.

---

## Phase 8 — Shopping Cart

**Step A**
- Cart is created lazily on first add; a user never has two carts (unique `user_id` enforced under concurrent adds).
- Add: unpurchased movie → 201; already purchased → 409 with an explicit message; duplicate in cart → 409; non-existent movie → 404.
- List: returns title, price, genres, and release year per item; empty cart → 200 with an empty list.
- Remove single item → 204; remove an item not in the cart → 404; clear cart → 204 and subsequent list is empty.
- Isolation: user A cannot read or mutate user B's cart → 403/404.
- Moderator: admin can read any user's cart; Moderator/User cannot read others'.
- Unauthenticated add → 401 (drives the "register before purchase" flow).

**Step B**
- `models/carts.py`: `Cart` (unique `user_id`), `CartItem` with unique `(cart_id, movie_id)` and `added_at`.
- `services/carts.py`: purchase-state check queries paid orders through the repository; one reusable `has_purchased(user_id, movie_ids)` helper consumed by cart **and** order validation.
- Admin cart-inspection endpoint behind `require_group(ADMIN)`.

**Step C**
- The purchase-state check exists once and is called from both Phase 8 and Phase 9.
- Coverage 100 % on `services/carts.py`.

---

## Phase 9 — Orders

**Step A**
- Place order: valid cart → 201, status `pending`, `total_amount` equals the sum of `price_at_order`, cart emptied of the ordered items.
- Empty cart → 400.
- Exclusions: already-purchased and unavailable/deleted movies are dropped from the order and reported in the response; if every item is excluded → 400 and no order row.
- Duplicate guard: a pending order already containing the same movie blocks a second pending order for it → 409.
- Price snapshot: changing a movie's price after order creation does not alter `price_at_order`; revalidation before payment recomputes and surfaces a changed total.
- Cancellation: `pending` → `canceled` allowed; `paid` → `canceled` rejected with a refund-required message; canceling another user's order → 403.
- Listing: user sees only their own orders with date, items, total, status.
- Admin listing: filters by user, date range, and status compose correctly; a User hitting the admin endpoint → 403.
- Concurrency: two simultaneous placements from the same cart create exactly one order.

**Step B**
- `models/orders.py`: `Order` (`status` enum defaulting to `pending`, `total_amount` `NUMERIC(10,2)`), `OrderItem` with immutable `price_at_order`.
- `services/orders.py`: placement, validation pipeline (reusing the Phase 8 purchase check), cancellation, revalidation. Status transitions defined as one explicit transition map — no scattered `if status ==` branches.
- Row-level locking on placement.

**Step C**
- Status transitions enumerated in a single structure and covered by a parametrised legal/illegal transition test.
- No float arithmetic anywhere in the money path (assert via a test on `Decimal` types).
- Coverage 100 % on `services/orders.py`.

---

## Phase 10 — Payments (Stripe)

**Step A**
- Checkout: creating a session for a `pending` order returns a redirect URL and persists `external_payment_id`; the order stays `pending` until the webhook lands.
- Authorisation: unauthenticated → 401; paying another user's order → 403; paying an already-paid order → 409; paying a canceled order → 400.
- Amount validation: a total that changed since order creation is revalidated and rejected/recomputed before the gateway call.
- Webhook: valid signed `payment_succeeded` → `Payment` created with `PaymentItem` rows mirroring the order items, order → `paid`, one confirmation email sent.
- Webhook idempotency: replaying the same event does not duplicate `Payment` rows and does not resend the email.
- Webhook security: invalid signature → 400 and no state change; unknown event type → 200 no-op.
- Failure path: `payment_failed` leaves the order `pending` and returns actionable guidance to the user.
- Refund: refund marks the payment `refunded`; only Admin may trigger it; a refunded movie is no longer counted as purchased.
- History: user sees date, amount, status for their own payments only; admin list filters by user, date, and status.
- Gateway outage: the fake gateway raising a transport error surfaces `ExternalServiceError` → 502 and leaves no partial rows.

**Step B**
- `models/payments.py`: `Payment` (enum status, `external_payment_id`, `NUMERIC(10,2)` amount), `PaymentItem` referencing `order_items` with `price_at_payment`.
- `integrations/payment/interface.py` `PaymentGatewayInterface` + Stripe implementation; **all tests run against `tests/doubles/` — never against live Stripe.**
- `services/payments.py`; webhook idempotency keyed on the external event/payment id inside a single transaction.
- Confirmation email via the existing email interface.

**Step C**
- No Stripe SDK import outside `integrations/payment/stripe_gateway.py`.
- Secrets exclusively from `Settings`; `.env.sample` documents every payment variable with placeholder values.
- Coverage 100 % on `services/payments.py`.

---

## Phase 11 — Media Storage, Documentation, CI/CD, Release

**Step A**
- Avatar upload: valid image → 200 with a stored key and retrievable URL; oversized file → 413; disallowed MIME type → 415; corrupt image → 422; upload for another user's profile → 403. All against the fake storage double.
- Swagger access control: anonymous `GET /docs` and `/openapi.json` → 401/403; authorised request → 200; the generated schema contains every router tag and no orphaned endpoints.
- Smoke: a full end-to-end scenario — register → activate → login → browse → favorite → add to cart → order → pay (fake webhook) → appears in purchased list — passes as one test.

**Step B**
- `integrations/storage/` interface + MinIO implementation; profile service stores only the key, never the raw URL.
- Swagger secured behind an auth dependency; custom `openapi()` with tags, descriptions, and documented error responses per endpoint.
- `README.md`: purpose, feature list, architecture diagram, env var table, `docker compose up` quickstart, migration and seed commands, test and coverage commands, API overview, contribution/branching rules.
- `.github/workflows/ci.yml` (lint → mypy → pytest → coverage gate) and `cd.yml` (deploy to EC2 on merge to `main`).

**Step C**
- Coverage report ≥ 85 % overall, 100 % on `services/` and `security/`; the gate fails the build below threshold.
- `mypy --strict src/` clean with zero unexplained ignores.
- A clean clone reaches a working stack via the documented commands only — no undocumented manual steps.
- Every phase branch merged via reviewed PR with a green pipeline.

---

## Phase Dependency Graph

```
0 → 1 → 2 → 3 → 4
         └→ 5 → 6 → 7
              └→ 8 → 9 → 10
                          └→ 11
```

Phases 6/7 and 8/9/10 may run on parallel branches once Phase 5 merges; both must rebase onto Phase 4 for auth dependencies.
