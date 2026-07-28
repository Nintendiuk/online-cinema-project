"""End-to-end tests for the health endpoint and unknown-route handling."""

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.e2e


async def test_health_endpoint_returns_ok(async_client: AsyncClient) -> None:
    """GET /health answers 200 with a body of exactly {"status": "ok"}."""
    response = await async_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_unknown_route_returns_404(async_client: AsyncClient) -> None:
    """An unregistered path answers 404."""
    response = await async_client.get("/definitely-not-a-real-route")

    assert response.status_code == 404
