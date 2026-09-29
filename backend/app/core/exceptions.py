from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ArchivoltError(Exception):
    pass


class NotFoundError(ArchivoltError):
    pass


class ForbiddenError(ArchivoltError):
    pass


class UnauthorizedError(ArchivoltError):
    pass


class ValidationError(ArchivoltError):
    pass


class InsufficientEvidenceError(ArchivoltError):
    pass


class IngestionError(ArchivoltError):
    pass


class StorageError(ArchivoltError):
    pass


class ProviderError(ArchivoltError):
    pass


class RateLimitError(ArchivoltError):
    def __init__(self, message: str = "Rate limit exceeded", retry_after: int = 1) -> None:
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))


class BudgetExceededError(ArchivoltError):
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
