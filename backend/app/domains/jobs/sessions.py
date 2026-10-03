"""The DB session source for background work: one place to patch in tests."""

from app.core.database import AsyncSessionLocal


def new_session():
    return AsyncSessionLocal()
