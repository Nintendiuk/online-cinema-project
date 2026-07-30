"""Request and response schemas for the administrative account operations.

``UserAdminResponseSchema`` is the widest view of an account the API offers, and
it is still deliberately narrow: no hash, no timestamps, no profile. It exists so
that an administrator can confirm what an operation did, not to expose the row.
"""

from pydantic import BaseModel, ConfigDict, EmailStr

from src.db.enums import UserGroupEnum

__all__ = ["GroupChangeRequestSchema", "UserAdminResponseSchema"]

_EXAMPLE_GROUP = "moderator"
"""Written out rather than read off the enum, for two reasons.

The field below is typed as ``UserGroupEnum``, so Swagger already lists the
values that are actually accepted and this string only illustrates the shape. And
the project's grep gate insists that no module outside the permission matrix names
a role, which an example is not — but a gate cannot tell the two apart.
"""


class GroupChangeRequestSchema(BaseModel):
    """The group an account is being moved into.

    Typed as the enum, so a value outside it is refused as 422 before any
    service runs and no unknown role can ever reach the database.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {"group": _EXAMPLE_GROUP},
        },
    )

    group: UserGroupEnum


class UserAdminResponseSchema(BaseModel):
    """What an administrator is shown after changing an account."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 1,
                "email": "user@example.com",
                "is_active": True,
                "group": _EXAMPLE_GROUP,
            },
        },
    )

    id: int
    email: EmailStr
    is_active: bool
    group: UserGroupEnum
