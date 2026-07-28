"""Aggregator for all version 1 routers.

Feature routers are included here as later phases add them; the prefix and tags
of each feature live in its own module.
"""

from fastapi import APIRouter

api_router = APIRouter()
