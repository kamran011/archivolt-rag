from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import settings
from app.core.database import engine
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import LoggingMiddleware, RequestIdMiddleware

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    # Verify DB connectivity on startup
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("database_connected")
    except Exception as e:
        logger.error("database_connection_failed", error=str(e))
    try:
        from app.domains.ingestion.background import recover_stuck_ingestions

        await recover_stuck_ingestions()
    except Exception as e:
        logger.error("stuck_ingestion_recovery_failed", error=str(e))
    yield
    await engine.dispose()


app = FastAPI(
    title="Archivolt API",
    version="0.1.0",
    description="AI Knowledge & Evidence Platform",
    lifespan=lifespan,
)

# Middleware (order matters — outermost first)
app.add_middleware(LoggingMiddleware)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)


@app.get("/health/ready", tags=["system"])
async def ready():
    """Readiness: verifies the database is reachable (503 otherwise). /health stays a
    cheap liveness probe."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        logger.error("readiness_check_failed", error=str(e))
        return JSONResponse(status_code=503, content={"status": "unavailable", "database": "down"})
    return {"status": "ready", "database": "up"}


@app.get("/health", tags=["system"])
async def health():
    return {"status": "healthy", "version": "0.1.0", "environment": settings.ENVIRONMENT}


from app.domains.analytics.router import router as analytics_router
from app.domains.auth.router import router as auth_router
from app.domains.chat.router import router as chat_router
from app.domains.documents.router import router as documents_router
from app.domains.ingestion.router import router as ingestion_router
from app.domains.knowledge_bases.router import router as kb_router
from app.domains.observability.router import router as observability_router
from app.domains.organizations.router import router as organizations_router
from app.domains.retrieval.router import router as retrieval_router

app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(organizations_router, prefix="/api/v1/organizations", tags=["organizations"])
app.include_router(kb_router, prefix="/api/v1/knowledge-bases", tags=["knowledge-bases"])
app.include_router(
    documents_router,
    prefix="/api/v1/knowledge-bases/{kb_id}/documents",
    tags=["documents"],
)
app.include_router(ingestion_router, prefix="/api/v1/ingestion", tags=["ingestion"])
app.include_router(retrieval_router, prefix="/api/v1/retrieval", tags=["retrieval"])
app.include_router(chat_router, prefix="/api/v1/chat", tags=["chat"])
app.include_router(
    observability_router, prefix="/api/v1/observability", tags=["observability"]
)
app.include_router(analytics_router, prefix="/api/v1/analytics", tags=["analytics"])
