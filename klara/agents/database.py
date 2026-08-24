"""
app/database.py
───────────────
Async SQLAlchemy engine + session factory.
Uses asyncpg driver for Postgres.

Engine and session factory are initialised lazily on first use so that
importing this module (e.g., in unit tests that mock the DB) does not
require asyncpg or a reachable DATABASE_URL at import time.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# ---------------------------------------------------------------------------
# Lazy engine / session factory
# ---------------------------------------------------------------------------

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker] = None  # type: ignore[type-arg]


def _get_engine() -> AsyncEngine:
    """Return the shared async engine, creating it on first call."""
    global _engine
    if _engine is None:
        settings = get_settings()
        # Strip any sslmode/ssl URL params — asyncpg requires ssl via connect_args,
        # not as a query string parameter.
        # Use ssl="require" (encrypts, no CA pinning) so the Hetzner CA cert does
        # not need to be baked into the container image.
        import re
        db_url = settings.database_url
        connect_args: dict = {}
        if "sslmode=" in db_url or "ssl=" in db_url:
            db_url = re.sub(r"[?&]ssl(mode)?=[^&]*", "", db_url).rstrip("?")
            connect_args["ssl"] = "require"

        _engine = create_async_engine(
            db_url,
            echo=settings.app_debug,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
    return _engine


def _get_session_factory() -> async_sessionmaker:  # type: ignore[type-arg]
    """Return the shared session factory, creating it on first call."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=_get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


# ---------------------------------------------------------------------------
# Public API — unchanged from callers' perspective
# ---------------------------------------------------------------------------

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a transactional async DB session."""
    async with _get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for use outside FastAPI request lifecycle (e.g., Celery tasks)."""
    async with _get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_async_session() -> async_sessionmaker:  # type: ignore[type-arg]
    """Return the session factory callable (alias used by some Celery tasks)."""
    return _get_session_factory()
