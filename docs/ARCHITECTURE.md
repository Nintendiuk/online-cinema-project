# Online Cinema — Architecture Specification

Stack baseline: Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · Alembic · PostgreSQL · Redis · Celery + celery-beat · MinIO (S3) · Stripe · Poetry · Docker Compose · pytest · mypy (strict) · ruff/black · GitHub Actions.

---

## 1. Directory Structure Blueprint

```
online-cinema-project/
├── src/
│   ├── main.py                          # ASGI factory only: create_app(), router mounting, middleware
│   │
│   ├── core/                            # cross-cutting, framework-agnostic
│   │   ├── config.py                    # BaseSettings; ONE settings object, env-driven
│   │   ├── constants.py
│   │   ├── exceptions.py                # domain exception hierarchy (see §5)
│   │   ├── pagination.py                # generic Page[T] + LimitOffsetParams — reused everywhere
│   │   ├── filtering.py                 # generic filter/sort spec -> SQLAlchemy clause builder
│   │   └── logging.py
│   │
│   ├── db/
│   │   ├── base.py                      # DeclarativeBase, naming_convention, TimestampMixin, IntPKMixin
│   │   ├── session.py                   # async_engine, async_sessionmaker, get_session generator
│   │   ├── enums.py                     # UserGroupEnum, GenderEnum, OrderStatusEnum, PaymentStatusEnum
│   │   └── seed/
│   │       ├── groups.py                # idempotent seeding of user_groups
│   │       └── movies_csv.py            # catalog import command
│   │
│   ├── models/                          # ONE module per bounded context. No business logic.
│   │   ├── __init__.py                  # re-export for Alembic autogenerate metadata discovery
│   │   ├── accounts.py                  # UserGroup, User, UserProfile, ActivationToken,
│   │   │                                # PasswordResetToken, RefreshToken
│   │   ├── movies.py                    # Genre, Star, Director, Certification, Movie,
│   │   │                                # MovieLike, MovieRating, MovieComment, CommentLike,
│   │   │                                # Favorite, + association tables
│   │   ├── carts.py                     # Cart, CartItem
│   │   ├── orders.py                    # Order, OrderItem
│   │   └── payments.py                  # Payment, PaymentItem
│   │
│   ├── schemas/                         # Pydantic v2 only. No ORM access.
│   │   ├── common.py                    # PageResponse[T], MessageResponse, ErrorResponse
│   │   ├── accounts.py
│   │   ├── profiles.py
│   │   ├── movies.py
│   │   ├── interactions.py              # likes, ratings, comments, favorites
│   │   ├── carts.py
│   │   ├── orders.py
│   │   └── payments.py
│   │
│   ├── repositories/                    # ONLY layer that touches AsyncSession
│   │   ├── base.py                      # BaseRepository[ModelT]: get, get_by, list, create,
│   │   │                                # update, delete, exists, count  ← DRY anchor
│   │   ├── accounts.py                  # UserRepository, TokenRepository (generic over token models)
│   │   ├── movies.py                    # MovieRepository, GenreRepository, StarRepository,
│   │   │                                # DirectorRepository, CertificationRepository
│   │   ├── interactions.py
│   │   ├── carts.py
│   │   ├── orders.py
│   │   └── payments.py
│   │
│   ├── services/                        # business rules. No FastAPI imports, no raw SQL.
│   │   ├── accounts/
│   │   │   ├── registration.py
│   │   │   ├── activation.py
│   │   │   ├── authentication.py
│   │   │   ├── password.py
│   │   │   └── admin.py                 # group changes, manual activation
│   │   ├── movies/
│   │   │   ├── catalog.py               # read: list/detail/search/filter/sort
│   │   │   ├── management.py            # moderator CRUD + delete guards
│   │   │   └── interactions.py          # like, rate, comment, reply, favorite
│   │   ├── carts.py
│   │   ├── orders.py
│   │   └── payments.py
│   │
│   ├── api/
│   │   ├── deps.py                      # get_session, get_current_user, require_group(...),
│   │   │                                # get_<X>_service — dependency wiring lives HERE only
│   │   └── v1/
│   │       ├── router.py                # aggregates all sub-routers, one prefix per resource
│   │       ├── accounts.py
│   │       ├── profiles.py
│   │       ├── movies.py
│   │       ├── genres.py
│   │       ├── interactions.py
│   │       ├── carts.py
│   │       ├── orders.py
│   │       └── payments.py              # incl. POST /webhooks/stripe
│   │
│   ├── security/
│   │   ├── passwords.py                 # hash/verify (bcrypt/argon2)
│   │   ├── validators.py                # password complexity, email normalisation
│   │   ├── jwt_manager.py               # JWTAuthManagerInterface + implementation
│   │   └── permissions.py               # group → permission matrix
│   │
│   ├── integrations/                    # every external system behind an ABC (see §3)
│   │   ├── email/
│   │   │   ├── interface.py             # EmailSenderInterface
│   │   │   ├── smtp_sender.py
│   │   │   └── templates/               # activation, password_reset, order_confirm, comment_reply
│   │   ├── storage/
│   │   │   ├── interface.py             # S3StorageInterface
│   │   │   └── minio_storage.py
│   │   └── payment/
│   │       ├── interface.py             # PaymentGatewayInterface
│   │       └── stripe_gateway.py
│   │
│   ├── tasks/
│   │   ├── celery_app.py                # app + beat_schedule
│   │   ├── tokens.py                    # purge_expired_activation_tokens, purge_refresh_tokens
│   │   └── emails.py                    # async email dispatch
│   │
│   └── validation/
│       └── movies.py                    # domain-level field validators reused by schemas
│
├── tests/
│   ├── conftest.py                      # engine, per-test transaction rollback, app override
│   ├── factories/                       # model factories — no inline fixture duplication
│   ├── unit/                            # validators, jwt, price math, filter builder
│   ├── integration/                      # repositories + services against real DB
│   ├── e2e/                             # full HTTP flows via httpx.AsyncClient
│   └── doubles/                          # fake email sender, fake storage, fake payment gateway
│
├── alembic/
│   ├── env.py
│   └── versions/
├── commands/                            # CLI entrypoints (seed, import catalog)
├── docker/
│   ├── web/Dockerfile
│   ├── celery/Dockerfile
│   └── entrypoint.sh
├── .github/workflows/
│   ├── ci.yml                           # lint → type → test → coverage gate
│   └── cd.yml                           # deploy to EC2 on main
├── docker-compose.yml
├── docker-compose.override.yml
├── pyproject.toml
├── .env.sample
├── README.md
└── docs/
    ├── ARCHITECTURE.md
    └── ROADMAP.md
```

---

## 2. Layer Contracts and Dependency Direction

Allowed import direction — strictly one-way:

```
api/routers  →  services  →  repositories  →  models
     ↓              ↓             ↓
  schemas        schemas      db/session
                    ↓
              integrations (via interface)
```

| Layer | May do | Must never do |
|---|---|---|
| `api/v1/*` | parse request, call one service method, map to response schema | contain `if`-based business rules, import `AsyncSession` directly, query models |
| `services/*` | orchestrate rules, transactions, raise domain exceptions | import `fastapi`, build SQL, call `session.execute` |
| `repositories/*` | build and run queries, return ORM objects/scalars | enforce business rules, raise HTTP exceptions |
| `models/*` | declare columns, relationships, constraints | contain query logic or validation beyond DB constraints |
| `schemas/*` | validate/serialize I/O | touch DB or services |
| `integrations/*` | talk to external systems through an ABC | be imported concretely by services (inject the interface) |

**Router rule:** a route handler is at most ~10 lines — dependencies in, one service call, return. Any handler that grows past that is a service extraction defect.

---

## 3. DRY Anchors (mandatory reuse points)

Duplication of any of the following is a review-blocking defect.

1. `repositories/base.py::BaseRepository` — all CRUD. Concrete repos add only specialised queries.
2. `core/pagination.py` — one `Page[T]` envelope and one `LimitOffsetParams` dependency for movies, favorites, orders, payments, comments.
3. `core/filtering.py` — one declarative filter/sort spec applied to movies **and** favorites (favorites reuse catalog filtering verbatim; do not fork it).
4. `security/validators.py` — one password-complexity validator used by registration, password change, and password reset.
5. Token models share a common mixin (`TokenMixin`: `token`, `expires_at`, `user_id`) and a single generic `TokenRepository`/token-lifecycle service parameterised by model — activation, reset, and refresh tokens must not each get their own copy-pasted issue/verify/purge logic.
6. `api/deps.py::require_group(...)` — one permission dependency factory. No per-router role checks.
7. `tests/factories/` — one factory per model; no ad-hoc object construction inside tests.
8. `integrations/*/interface.py` — services depend on the ABC; tests inject the double from `tests/doubles/`.

---

## 4. Transaction and Consistency Rules

- One request = one transaction; the session dependency owns commit/rollback. Services never commit mid-flow except where a documented boundary requires it.
- Money is `Decimal` end to end. `NUMERIC(10,2)` in DB, `condecimal(max_digits=10, decimal_places=2)` in schemas. Float arithmetic on prices is prohibited.
- Historical price snapshots (`OrderItem.price_at_order`, `PaymentItem.price_at_payment`) are written once and are immutable.
- Order placement and payment confirmation run under row-level locking on the affected order to prevent double purchase.
- Stripe webhook handling is idempotent, keyed on `external_payment_id`; replays must not create duplicate `Payment` rows.
- All timestamps are `TIMESTAMP WITH TIME ZONE`, UTC.

---

## 5. Error Taxonomy

Single hierarchy in `core/exceptions.py`; one exception-handler registration in `main.py` maps domain → HTTP. Routers do not raise `HTTPException` directly.

```
AppError
├── ValidationError        → 422
├── NotFoundError          → 404
├── ConflictError          → 409   (duplicate email, movie already in cart/purchased)
├── AuthenticationError    → 401   (bad credentials, expired/invalid token)
├── PermissionDeniedError  → 403
├── TokenExpiredError      → 400   (activation/reset link expired)
└── ExternalServiceError   → 502   (Stripe, SMTP, S3)
```

---

## 6. Naming & Sizing Conventions

- Modules ≤ 300 lines; classes ≤ 150; functions ≤ 40. Exceeding a cap requires splitting, not a waiver.
- Repository methods: `get_*`, `list_*`, `create_*`, `update_*`, `delete_*`, `exists_*`, `count_*`.
- Service methods read as use cases: `register_user`, `activate_account`, `place_order`, `refund_payment`.
- Schemas suffixed by role: `MovieCreateSchema`, `MovieUpdateSchema`, `MovieListItemSchema`, `MovieDetailSchema`. Never reuse an input schema as an output schema.
- Alembic: one migration per phase, descriptive slug, downgrade must be implemented and tested.

---

## 7. Typing & Quality Gates

- `mypy --strict` on `src/`. No `Any` in signatures; no bare `# type: ignore` without an error code and a comment.
- All public functions fully annotated, including return types.
- `ruff` + `black` clean; `ruff` rule set includes `E,F,I,B,UP,SIM,C4,ANN`.
- Coverage gate ≥ 85 % overall, 100 % on `services/` and `security/`.
- CI fails the build on any gate; no local-only verification.
