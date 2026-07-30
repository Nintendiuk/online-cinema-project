"""Administrative account operations.

The whole router sits behind ``ADMIN_ONLY``, declared once on the router rather
than repeated on each route: a route added here is guarded by construction, and
forgetting the decorator is not a mistake it is possible to make. Nothing in this
module names a group — the guard is built in the wiring layer and the response
reads the account's group as data.

Both handlers answer with the same view of the account, so an administrator can
see the state their operation produced instead of having to read it back.
"""

from fastapi import APIRouter, status

from src.api.deps import ADMIN_ONLY
from src.api.providers import AdminServiceDep
from src.models.accounts import User
from src.schemas.admin import GroupChangeRequestSchema, UserAdminResponseSchema

__all__ = ["router"]

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[ADMIN_ONLY],
    responses={
        401: {"description": "No bearer token, or one that is invalid or expired."},
        403: {"description": "The caller is authenticated but not an administrator."},
    },
)


def _as_admin_view(user: User) -> UserAdminResponseSchema:
    """Render an account as the administrative response body.

    The mapping lives here because presentation is the router's job, and it is a
    function rather than a schema classmethod so that ``src/schemas`` keeps
    knowing nothing about the ORM.
    """
    return UserAdminResponseSchema(
        id=user.id,
        email=user.email,
        is_active=user.is_active,
        group=user.group.name,
    )


@router.patch(
    "/users/{user_id}/group/",
    response_model=UserAdminResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Move an account into another group",
    responses={
        404: {"description": "No account with this id, or the group is unseeded."},
        422: {"description": "The group is not one of the known groups."},
    },
)
async def change_group(
    user_id: int,
    payload: GroupChangeRequestSchema,
    service: AdminServiceDep,
) -> UserAdminResponseSchema:
    """Set the group of one account; the change applies to its next request."""
    return _as_admin_view(await service.change_group(user_id, payload.group))


@router.post(
    "/users/{user_id}/activate/",
    response_model=UserAdminResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Activate an account without its e-mail token",
    responses={
        400: {"description": "The account is already active."},
        404: {"description": "No account with this id."},
    },
)
async def activate_account(
    user_id: int,
    service: AdminServiceDep,
) -> UserAdminResponseSchema:
    """Activate one account by hand and drop its pending activation token."""
    return _as_admin_view(await service.activate_manually(user_id))
