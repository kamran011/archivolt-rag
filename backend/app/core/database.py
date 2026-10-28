from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.SUPABASE_DB_URL,
    pool_size=20,
    max_overflow=10,
    pool_recycle=300,
    pool_pre_ping=True,
    # asyncpg's real kwarg is statement_cache_size (not prepared_statement_cache_size, which
    # SQLAlchemy's asyncpg dialect silently drops). Required at 0 when connecting through
    # pgbouncer in transaction/statement pooling mode (e.g. Supabase's pooler on :6543) —
    # otherwise asyncpg's server-side prepared statements collide across pooled connections
    # with DuplicatePreparedStatementError.
    connect_args={"statement_cache_size": 0},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Request-scoped session that commits when the endpoint returns.

    Always inject it as `Depends(get_db, scope="function")`: with the default "request" scope
    FastAPI runs this exit code *after* the response has been sent, so a client can get its 201
    and issue the next request before the commit lands (e.g. "Not a member of this
    organization" immediately after creating the organization), and a failed commit can no
    longer turn the response into an error."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
