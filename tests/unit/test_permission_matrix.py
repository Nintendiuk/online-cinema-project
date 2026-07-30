"""Unit tests for the group-to-permission matrix.

The matrix is the only place in ``src`` where a role is compared to anything, so
its shape is worth pinning directly rather than only through the endpoints that
consult it. What matters is that it is genuinely hierarchical: every right a
moderator holds is also an administrator's, and every right a plain user holds is
also a moderator's. A later phase that adds a permission to the middle row
without adding it to the top would otherwise pass every endpoint test and quietly
lock administrators out.
"""

import pytest

from src.db.enums import UserGroupEnum
from src.security.permissions import (
    GROUP_PERMISSIONS,
    Permission,
    belongs_to_any,
    has_permission,
)

pytestmark = pytest.mark.unit


def test_every_group_has_a_row() -> None:
    """No group can be left out of the matrix."""
    assert set(GROUP_PERMISSIONS) == set(UserGroupEnum)


def test_rows_are_immutable() -> None:
    """Each row is a frozenset, so no caller can widen it at runtime."""
    assert all(
        isinstance(permissions, frozenset)
        for permissions in GROUP_PERMISSIONS.values()
    )


def test_the_hierarchy_is_strictly_increasing() -> None:
    """USER ⊂ MODERATOR ⊂ ADMIN, each level adding at least one right."""
    assert (
        GROUP_PERMISSIONS[UserGroupEnum.USER]
        < GROUP_PERMISSIONS[UserGroupEnum.MODERATOR]
        < GROUP_PERMISSIONS[UserGroupEnum.ADMIN]
    )


def test_administrators_hold_every_permission() -> None:
    """The top of the hierarchy is the whole enumeration."""
    assert GROUP_PERMISSIONS[UserGroupEnum.ADMIN] == frozenset(Permission)


@pytest.mark.parametrize("permission", sorted(Permission))
def test_every_permission_is_reachable_and_inherited(permission: Permission) -> None:
    """A permission granted lower down is granted at every level above it."""
    holders = [
        group for group in UserGroupEnum if has_permission(group, permission)
    ]

    assert holders, f"{permission} is granted to nobody"
    assert has_permission(UserGroupEnum.ADMIN, permission)


@pytest.mark.parametrize(
    ("group", "permission", "expected"),
    [
        (UserGroupEnum.USER, Permission.BROWSE_CATALOG, True),
        (UserGroupEnum.USER, Permission.MANAGE_MOVIES, False),
        (UserGroupEnum.USER, Permission.VIEW_SALES, False),
        (UserGroupEnum.USER, Permission.MANAGE_USERS, False),
        (UserGroupEnum.MODERATOR, Permission.BROWSE_CATALOG, True),
        (UserGroupEnum.MODERATOR, Permission.MANAGE_MOVIES, True),
        (UserGroupEnum.MODERATOR, Permission.VIEW_SALES, True),
        (UserGroupEnum.MODERATOR, Permission.MANAGE_USERS, False),
        (UserGroupEnum.ADMIN, Permission.MANAGE_USERS, True),
        (UserGroupEnum.ADMIN, Permission.MANAGE_MOVIES, True),
    ],
)
def test_has_permission(
    group: UserGroupEnum, permission: Permission, expected: bool
) -> None:
    """The helper answers the matrix and nothing else."""
    assert has_permission(group, permission) is expected


def test_managing_users_is_reserved_for_administrators() -> None:
    """Nobody below the top row may change groups or activate accounts by hand."""
    holders = {
        group
        for group in UserGroupEnum
        if has_permission(group, Permission.MANAGE_USERS)
    }

    assert holders == {UserGroupEnum.ADMIN}


@pytest.mark.parametrize(
    ("group", "allowed", "expected"),
    [
        (UserGroupEnum.ADMIN, (UserGroupEnum.ADMIN,), True),
        (UserGroupEnum.MODERATOR, (UserGroupEnum.ADMIN,), False),
        (
            UserGroupEnum.MODERATOR,
            (UserGroupEnum.ADMIN, UserGroupEnum.MODERATOR),
            True,
        ),
        (UserGroupEnum.USER, (), False),
    ],
)
def test_belongs_to_any(
    group: UserGroupEnum, allowed: tuple[UserGroupEnum, ...], expected: bool
) -> None:
    """Group membership is a plain containment test, with no hierarchy implied.

    Deliberately not hierarchical: ``require_group(MODERATOR)`` names the groups
    it will accept, and an administrator is included only when the caller lists
    them. Inheritance belongs to the permission side of this module.
    """
    assert belongs_to_any(group, frozenset(allowed)) is expected
