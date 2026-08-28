"""
klara/rarv/runtime.py
─────────────────────
Minimal runtime shim for the ported RARV pipeline.

Provides the dependencies the 1:1-ported RARV code imports from the
monolith's `app.*` package structure:

  - db_context()     — async SQLAlchemy session (from DATABASE_URL)
  - get_settings()    — settings from env vars
  - Base              — SQLAlchemy DeclarativeBase
  - AgentContext      — dataclass passed to agent run()
  - AgentResult       — standardised agent return
  - BaseAgent         — abstract base for agents
  - PermissionLevel   — P1-P5 enum
  - celery_app        — no-op stub (decorator returns fn unchanged)
  - notes_service     — reads daily notes from the local vault clone

This module is the ONLY new code in the RARV port — everything else
is a 1:1 copy from the monolith with import/brand renames.
"""
from __future__ import annotations

import abc
import asyncio as _asyncio
import os
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

import structlog
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

logger = structlog.get_logger(__name__)

# T-INF-13: asyncpg doesn't expose ssl_handshake_timeout; asyncio default is 60s.
# WG tunnel + Azure PG SSL handshake occasionally exceeds that. Bump to 180s.
if not getattr(_asyncio.base_events.BaseEventLoop, "_klaravex_tls_patched", False):
    _orig_start_tls = _asyncio.base_events.BaseEventLoop.start_tls

    async def _patched_start_tls(self, *args, **kwargs):
        kwargs.setdefault("ssl_handshake_timeout", 180)
        return await _orig_start_tls(self, *args, **kwargs)

    _asyncio.base_events.BaseEventLoop.start_tls = _patched_start_tls
    _asyncio.base_events.BaseEventLoop._klaravex_tls_patched = True


# ════════════════════════════════════════════════════════════════════════
# PermissionLevel
# ════════════════════════════════════════════════════════════════════════

import enum


class PermissionLevel(str, enum.Enum):
    P1 = "P1"  # read-only
    P2 = "P2"  # internal write
    P3 = "P3"  # outbound / publish
    P4 = "P4"  # legal / billing
    P5 = "P5"  # client environment


# ════════════════════════════════════════════════════════════════════════
# Settings (lightweight — reads from env, no pydantic dependency)
# ════════════════════════════════════════════════════════════════════════


class _Settings:
    """Minimal settings loaded from environment variables."""

    def __init__(self) -> None:
        self.app_env = os.environ.get("APP_ENV", "production")
        self.app_debug = os.environ.get("APP_DEBUG", "").lower() in ("1", "true", "yes")
        self.database_url = os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://localhost/klaravex",
        )
        self.db_schema = os.environ.get("DB_SCHEMA", "klaravex")
        self.github_vault_token = os.environ.get("GITHUB_VAULT_TOKEN", "")
        self.github_vault_repo = os.environ.get(
            "GITHUB_VAULT_REPO", "astewarttcml-netizen/klaravex-vault"
        )
        self.github_vault_branch = os.environ.get("GITHUB_VAULT_BRANCH", "main")
        self.vault_path = os.environ.get(
            "VAULT_PATH",
            "/home/anthony/.claude/knowledge/klaravex-vault",
        )
        # LiteLLM gateway
        self.litellm_base_url = os.environ.get("LITELLM_BASE_URL", "http://localhost:8000")
        self.litellm_api_key = os.environ.get("LITELLM_API_KEY", "")
        # OpenAI (for embeddings in vault-mcp, not RARV directly)
        self.openai_api_key = os.environ.get("OPENAI_API_KEY", "")


_settings: Optional[_Settings] = None


def get_settings() -> _Settings:
    global _settings
    if _settings is None:
        # Load environment from .env.rarv if running in RARV context
        import os
        from pathlib import Path
        try:
            # Try to load the RARV env file if it exists
            env_file = Path(__file__).parent / ".env.rarv"
            if env_file.exists():
                with open(env_file, 'r') as f:
                    for line in f:
                        if line.strip() and not line.startswith('#'):
                            key, value = line.strip().split('=', 1)
                            os.environ[key] = value
        except Exception:
            # If we can't load the env file, continue with existing env vars
            pass
        _settings = _Settings()
    return _settings


# ════════════════════════════════════════════════════════════════════════
# SQLAlchemy Base + db_context
# ════════════════════════════════════════════════════════════════════════


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker] = None  # type: ignore[type-arg]


def _get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        db_url = settings.database_url
        connect_args: dict = {}
        if "sslmode=" in db_url or "ssl=" in db_url:
            db_url = re.sub(r"[?&]ssl(mode)?=[^&]*", "", db_url).rstrip("?")
            connect_args["ssl"] = "require"
            connect_args["timeout"] = 120

        _schema = (settings.db_schema or "").strip()
        if _schema and _schema != "public":
            connect_args["server_settings"] = {"search_path": f"{_schema},public"}

        _engine = create_async_engine(
            db_url,
            echo=settings.app_debug,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=1800,
            pool_reset_on_return="rollback",
            connect_args=connect_args,
        )
    return _engine


def _get_session_factory() -> async_sessionmaker:  # type: ignore[type-arg]
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=_get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


@asynccontextmanager
async def db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for standalone async DB sessions (replaces app.database.db_context)."""
    async with _get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ════════════════════════════════════════════════════════════════════════
# Agent base classes (replaces app.agents.base)
# ════════════════════════════════════════════════════════════════════════


@dataclass
class AgentContext:
    """Shared context passed to every agent invocation."""
    db: AsyncSession
    settings: _Settings
    conversation_id: str | None = None
    lead_id: str | None = None
    request_id: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentResult:
    """Standardised return from every agent run() call."""
    success: bool
    output: Any = None
    error: str | None = None
    approval_required: bool = False
    approval_id: str | None = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def ok(cls, output: Any = None, **meta) -> "AgentResult":
        return cls(success=True, output=output, metadata=meta)

    @classmethod
    def fail(cls, error: str, **meta) -> "AgentResult":
        return cls(success=False, error=error, metadata=meta)


class BaseAgent(abc.ABC):
    """Abstract base for all agents (replaces app.agents.base.BaseAgent)."""

    name: str
    description: str
    permission_level: PermissionLevel = PermissionLevel.P1

    @abc.abstractmethod
    async def run(self, context: AgentContext, inputs: dict) -> AgentResult:
        ...


# ════════════════════════════════════════════════════════════════════════
# Celery stub (replaces app.tasks.celery_app.celery_app)
# ════════════════════════════════════════════════════════════════════════


class _CeleryStub:
    """No-op Celery stub — @celery_app.task returns the function unchanged."""

    def task(self, *args, **kwargs):
        # Used as @celery_app.task or @celery_app.task(name=...)
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]

        def decorator(fn):
            return fn

        return decorator


celery_app = _CeleryStub()
celery_klaravex = celery_app  # alias for klaravex-side Celery stub


def configure_logging(debug: bool = False) -> None:
    """Minimal structlog setup (replaces app.core.logging.configure_logging)."""
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20 if not debug else 10),
    )


# ════════════════════════════════════════════════════════════════════════
# notes_service (replaces app.services.notes — vault read helpers)
# ════════════════════════════════════════════════════════════════════════


class _NotesService:
    """Read-only vault access (replaces app.services.notes)."""

    def _vault_root(self) -> Path:
        return Path(get_settings().vault_path)

    def _read_file(self, rel_path: str) -> Optional[str]:
        p = self._vault_root() / rel_path
        if not p.is_file():
            return None
        return p.read_text(encoding="utf-8", errors="replace")

    def read_daily(self, day: Optional[date] = None) -> Optional[str]:
        if day is None:
            day = date.today()
        return self._read_file(f"daily/{day.isoformat()}.md")

    def list_daily_notes(self, since: Optional[date] = None) -> list[date]:
        root = self._vault_root() / "daily"
        if not root.is_dir():
            return []
        dates = []
        for p in root.iterdir():
            if not p.is_file() or p.suffix != ".md":
                continue
            try:
                d = date.fromisoformat(p.stem)
            except ValueError:
                continue
            if since is None or d >= since:
                dates.append(d)
        return sorted(dates)

    def read_memory(self) -> Optional[str]:
        return self._read_file("MEMORY.md")

    def read_context(self) -> Optional[str]:
        return self._read_file("CONTEXT.md")

    def read_topic(self, slug: str) -> Optional[str]:
        return self._read_file(f"topics/{slug}.md")


notes_service = _NotesService()
notes = notes_service  # alias so `from klara.rarv.runtime import notes` works


def _vault_root() -> Path:
    """Module-level helper for journal agents that import _vault_root directly."""
    return notes_service._vault_root()
