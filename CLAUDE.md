# Engineering Standards — Online Cinema

Binding rules for all contributors and agents on this repository. See `docs/ARCHITECTURE.md` for structure and `docs/ROADMAP.md` for phase tasks.

## 1. TDD — hard gate

- Tests are written and committed **before** implementation, in a separate commit that shows them failing.
- Every task follows Step A (tests) → Step B (implementation) → Step C (verification).
- A PR whose first implementation commit precedes its test commit is rejected.
- No test is modified to accommodate a defect; fix the code.

## 2. DRY

- Before writing a helper, search for an existing one. Second occurrence of a pattern is refactored immediately, not "later".
- Mandatory reuse points (duplication here blocks merge): `BaseRepository`, `core/pagination.py`, `core/filtering.py`, password validator, token-lifecycle helper, `require_group`, test factories, integration interfaces.

## 3. Layering

- Import direction is one-way: `api → services → repositories → models`.
- `AsyncSession` appears only in `repositories/` and `db/`.
- `fastapi` is never imported inside `services/`.
- Route handlers are ≤ 10 lines: dependencies in, one service call, return.
- External systems (SMTP, S3, Stripe) are accessed only through an ABC in `integrations/`; services receive the interface by injection.

## 4. Sizing

- Modules ≤ 300 lines, classes ≤ 150, functions ≤ 40. Split rather than waive.
- One bounded context per model/schema/repository/service module. No `utils.py` dumping ground.

## 5. Typing

- `mypy --strict` on `src/` must pass. Full annotations including returns.
- No `Any` in public signatures. `# type: ignore` requires an error code and a justifying comment.

## 6. Data & money

- Money is `Decimal` end to end; `NUMERIC(10,2)` in DB. Float arithmetic on prices is prohibited.
- Timestamps are timezone-aware UTC.
- Price snapshots (`price_at_order`, `price_at_payment`) are immutable once written.

## 7. Configuration

- All configuration flows through the single `Settings` object. `os.getenv` outside `core/config.py` is prohibited.
- Every variable is documented in `.env.sample` with a placeholder. Secrets are never committed.

## 8. Errors

- Domain exceptions from `core/exceptions.py`; HTTP mapping happens once in the exception handler. `HTTPException` is not raised in routers or services.
- Auth-related responses must not leak account existence.

## 9. Git

- Branch per phase: `phase-<n>-<slug>`. Commits: `<type>(<scope>): <imperative summary>`.
- Small, frequent, self-describing commits. Merge via reviewed PR with a green pipeline only.

## 10. Verification gates (CI-enforced)

- `ruff` + `black --check` clean.
- `mypy --strict src/` clean.
- `pytest` green; coverage ≥ 85 % overall and 100 % on `services/` and `security/`.
- Alembic autogenerate diff empty against head.
- External services are never contacted in tests; use the doubles in `tests/doubles/`.
