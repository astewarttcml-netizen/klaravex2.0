"""Re-export shim — canonical implementation lives in infra/lib/db.py.

All klara.handlers modules that use ``from .lib.db import get_pool`` continue
to work unchanged; the singleton pool is owned by lib.db.
"""
from lib.db import (  # noqa: F401
    normalize_dsn,
    get_pool,
    close_pool,
    healthcheck,
)
