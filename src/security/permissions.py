"""The group-to-permission matrix.

The only module in ``src`` where a role is compared to anything. Everywhere else
asks a question — "may this group do this?" — and never inspects the group
itself, which is what keeps a new role or a moved right a one-line change here
instead of a search through the routers.

The matrix is hierarchical by construction rather than by convention: each row is
built from the one below it, so a right granted to a plain user cannot be missing
from a moderator, and a right granted to a moderator cannot be missing from an
administrator. Editing a row means adding to a union, not retyping a set.

Group membership (``belongs_to_any``) is deliberately *not* hierarchical.
``require_group`` names the groups it accepts and means exactly those; anything
that should widen with rank belongs on the permission side.
"""

from collections.abc import Collection, Mapping
from enum import StrEnum
from types import MappingProxyType

from src.db.enums import UserGroupEnum

__all__ = [
    "GROUP_PERMISSIONS",
    "Permission",
    "belongs_to_any",
    "has_permission",
]


class Permission(StrEnum):
    """A single capability a group may or may not hold.

    Named after the operation rather than the endpoint, so that a route which
    moves or splits in a later phase does not invalidate the name.
    """

    BROWSE_CATALOG = "browse_catalog"
    RATE_AND_COMMENT = "rate_and_comment"
    PURCHASE_TICKETS = "purchase_tickets"
    MANAGE_MOVIES = "manage_movies"
    MODERATE_COMMENTS = "moderate_comments"
    VIEW_SALES = "view_sales"
    MANAGE_USERS = "manage_users"


_USER_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.BROWSE_CATALOG,
        Permission.RATE_AND_COMMENT,
        Permission.PURCHASE_TICKETS,
    }
)

_MODERATOR_PERMISSIONS: frozenset[Permission] = _USER_PERMISSIONS | {
    Permission.MANAGE_MOVIES,
    Permission.MODERATE_COMMENTS,
    Permission.VIEW_SALES,
}

_ADMIN_PERMISSIONS: frozenset[Permission] = _MODERATOR_PERMISSIONS | {
    Permission.MANAGE_USERS,
}

GROUP_PERMISSIONS: Mapping[UserGroupEnum, frozenset[Permission]] = MappingProxyType(
    {
        UserGroupEnum.USER: _USER_PERMISSIONS,
        UserGroupEnum.MODERATOR: _MODERATOR_PERMISSIONS,
        UserGroupEnum.ADMIN: _ADMIN_PERMISSIONS,
    }
)
"""Every group in the project and the rights it holds.

A read-only mapping of frozensets: nothing at runtime can widen a role, so a
permission check cannot be defeated by a caller that mutates the table.
"""


def has_permission(group: UserGroupEnum, permission: Permission) -> bool:
    """Whether this group holds this permission.

    A group with no row holds nothing, rather than raising: an unseeded or
    retired group must fail closed.
    """
    return permission in GROUP_PERMISSIONS.get(group, frozenset())


def belongs_to_any(group: UserGroupEnum, allowed: Collection[UserGroupEnum]) -> bool:
    """Whether this group is one of the groups a route accepts."""
    return group in allowed
