"""Domain enumerations for the Online Cinema backend."""

from enum import StrEnum


class UserGroupEnum(StrEnum):
    """User access groups persisted as a native enum in PostgreSQL."""

    USER = "user"
    MODERATOR = "moderator"
    ADMIN = "admin"


class GenderEnum(StrEnum):
    """User profile gender persisted as a native enum in PostgreSQL."""

    MAN = "man"
    WOMAN = "woman"
