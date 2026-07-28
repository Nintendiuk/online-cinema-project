"""Application factory and the single place where domain errors become HTTP."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.v1.router import api_router
from src.core.config import get_settings
from src.core.exceptions import (
    AppError,
    AuthenticationError,
    ConflictError,
    ExternalServiceError,
    NotFoundError,
    PermissionDeniedError,
    TokenExpiredError,
    ValidationError,
)

ERROR_STATUS_CODES: dict[type[AppError], int] = {
    ValidationError: 422,
    NotFoundError: 404,
    ConflictError: 409,
    AuthenticationError: 401,
    PermissionDeniedError: 403,
    TokenExpiredError: 400,
    ExternalServiceError: 502,
}
DEFAULT_ERROR_STATUS_CODE = 500


def status_code_for(error: AppError) -> int:
    """Return the HTTP status code registered for the error's closest ancestor."""
    for error_type in type(error).__mro__:
        if error_type in ERROR_STATUS_CODES:
            return ERROR_STATUS_CODES[error_type]
    return DEFAULT_ERROR_STATUS_CODE


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render any domain error as a JSON problem body with its status code."""
    if not isinstance(exc, AppError):  # pragma: no cover - defensive guard
        raise exc
    return JSONResponse(
        status_code=status_code_for(exc),
        content={"detail": exc.message, "details": exc.details},
    )


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()
    app = FastAPI(
        title="Online Cinema",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        """Liveness probe used by Docker and by monitoring."""
        return {"status": "ok"}

    return app
