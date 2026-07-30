"""End-to-end tests for role-based access control.

One parametrised table covers every guarded route the project has, crossed with
every group. The table is the point: each later phase adds rows to it rather than
another test function, so the cost of guarding a new endpoint stays one line.

The probe at the bottom exercises ``require_permission``, which no production
route uses yet — the matrix it consults is what phases 5 and later will guard
moderator endpoints with, and an untested dependency factory is a defect waiting
for its first caller.
"""

from collections.abc import Callable
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import require_permission
from src.db.enums import UserGroupEnum
from src.models.accounts import User
from src.security.permissions import Permission
from tests.e2e.rbac_support import (
    SALES_PROBE_URL,
    caller_in_group,
    group_change_url,
    manual_activation_url,
    user_in_group,
)

pytestmark = pytest.mark.e2e

GUARDED_ROUTES: list[tuple[str, Callable[[int], str], dict[str, Any] | None]] = [
    ("PATCH", group_change_url, {"group": UserGroupEnum.MODERATOR.value}),
    ("POST", manual_activation_url, None),
]
"""Every route behind a group guard, as ``(method, url builder, body)``."""

ROUTE_IDS = ["admin-group-change", "admin-manual-activation"]

GROUP_EXPECTATIONS = [
    (UserGroupEnum.USER, 403),
    (UserGroupEnum.MODERATOR, 403),
    (UserGroupEnum.ADMIN, 200),
]
"""What each group may expect from an admin-only route."""

GROUP_IDS = ["user", "moderator", "admin"]

SalesViewerDep = Annotated[User, Depends(require_permission(Permission.VIEW_SALES))]
"""Guard for the throwaway sales probe defined further down."""


@pytest.mark.parametrize(("method", "url_for", "body"), GUARDED_ROUTES, ids=ROUTE_IDS)
@pytest.mark.parametrize(("group", "expected"), GROUP_EXPECTATIONS, ids=GROUP_IDS)
async def test_guarded_routes_enforce_the_group_matrix(
    async_client: AsyncClient,
    db_session: AsyncSession,
    method: str,
    url_for: Callable[[int], str],
    body: dict[str, Any] | None,
    group: UserGroupEnum,
    expected: int,
) -> None:
    """Only an administrator gets through; the others are refused with 403."""
    headers = await caller_in_group(db_session, group)
    target = await user_in_group(
        db_session, UserGroupEnum.USER, email="target@example.com", is_active=False
    )

    response = await async_client.request(
        method, url_for(target.id), json=body, headers=headers
    )

    assert response.status_code == expected


@pytest.mark.parametrize(("method", "url_for", "body"), GUARDED_ROUTES, ids=ROUTE_IDS)
async def test_guarded_routes_answer_401_without_credentials(
    async_client: AsyncClient,
    db_session: AsyncSession,
    method: str,
    url_for: Callable[[int], str],
    body: dict[str, Any] | None,
) -> None:
    """An anonymous caller fails authentication before authorisation is reached.

    401 and not 403: the server cannot say the caller lacks a group when it does
    not yet know who the caller is.
    """
    target = await user_in_group(
        db_session, UserGroupEnum.USER, email="target@example.com", is_active=False
    )

    response = await async_client.request(method, url_for(target.id), json=body)

    assert response.status_code == 401


@pytest.fixture
def sales_probe(app: FastAPI) -> FastAPI:
    """Mount a throwaway route guarded by a permission rather than a group.

    Defined here rather than in ``conftest`` because exactly one module needs it,
    and production has no sales endpoint until a later phase.
    """

    @app.get(SALES_PROBE_URL)
    async def sales(current_user: SalesViewerDep) -> dict[str, int]:
        """Echo the id of a caller allowed to look at sales figures."""
        return {"user_id": current_user.id}

    return app


class TestRequirePermission:
    """``require_permission`` consults the matrix instead of naming a group."""

    @pytest.mark.parametrize(
        ("group", "expected"),
        [
            (UserGroupEnum.USER, 403),
            (UserGroupEnum.MODERATOR, 200),
            (UserGroupEnum.ADMIN, 200),
        ],
        ids=GROUP_IDS,
    )
    async def test_view_sales_is_granted_from_moderator_upwards(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
        sales_probe: FastAPI,
        group: UserGroupEnum,
        expected: int,
    ) -> None:
        """The hierarchy is honoured: an admin inherits every moderator right."""
        headers = await caller_in_group(db_session, group)

        response = await async_client.get(SALES_PROBE_URL, headers=headers)

        assert response.status_code == expected

    async def test_anonymous_caller_is_unauthorised(
        self, async_client: AsyncClient, sales_probe: FastAPI
    ) -> None:
        """The permission guard composes with the authentication dependency."""
        response = await async_client.get(SALES_PROBE_URL)

        assert response.status_code == 401
