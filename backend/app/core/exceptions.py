from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class GroundtruthError(Exception):
    pass


class NotFoundError(GroundtruthError):
    pass


class ForbiddenError(GroundtruthError):
    pass


class UnauthorizedError(GroundtruthError):
    pass


class ValidationError(GroundtruthError):
    pass


class InsufficientEvidenceError(GroundtruthError):
    pass


class IngestionError(GroundtruthError):
    pass


class StorageError(GroundtruthError):
    pass


class ProviderError(GroundtruthError):
    """An upstream LLM/embedding provider call failed. The message is safe to show to users:
    provider error bodies can quote parts of the API key, so build it with
    `provider_error()` rather than interpolating the raw exception."""


def provider_error(provider: str, operation: str, exc: BaseException) -> ProviderError:
    """Classifies a provider SDK exception into a user-safe ProviderError, logging only the
    exception type and HTTP status (never its message)."""
    import structlog

    status = getattr(exc, "status_code", None)
    structlog.get_logger().error(
        "provider_call_failed",
        provider=provider,
        operation=operation,
        error_type=type(exc).__name__,
        status=status,
    )
    if status in (401, 403):
        reason = "the provider rejected the server's API credentials"
    elif status == 429:
        reason = "the provider rate limit or quota was reached"
    elif status is not None and status >= 500:
        reason = "the provider is temporarily unavailable"
    elif "timeout" in type(exc).__name__.lower():
        reason = "the provider timed out"
    else:
        reason = "an unexpected provider error occurred"
    return ProviderError(f"{provider} {operation} failed: {reason}")


class RateLimitError(GroundtruthError):
    def __init__(self, message: str = "Rate limit exceeded", retry_after: int = 1) -> None:
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))


class BudgetExceededError(GroundtruthError):
    """The organization has used its daily LLM budget."""


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(UnauthorizedError)
    async def unauthorized_handler(request: Request, exc: UnauthorizedError) -> JSONResponse:
        return JSONResponse(status_code=401, content={"detail": str(exc) or "Unauthorized"})

    @app.exception_handler(ForbiddenError)
    async def forbidden_handler(request: Request, exc: ForbiddenError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc) or "Forbidden"})

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc) or "Not found"})

    @app.exception_handler(ValidationError)
    async def validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(IngestionError)
    async def ingestion_handler(request: Request, exc: IngestionError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.exception_handler(StorageError)
    async def storage_handler(request: Request, exc: StorageError) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.exception_handler(ProviderError)
    async def provider_handler(request: Request, exc: ProviderError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(RateLimitError)
    async def rate_limit_handler(request: Request, exc: RateLimitError) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={"detail": str(exc)},
            headers={"Retry-After": str(exc.retry_after)},
        )

    @app.exception_handler(BudgetExceededError)
    async def budget_handler(request: Request, exc: BudgetExceededError) -> JSONResponse:
        return JSONResponse(status_code=429, content={"detail": str(exc)})
