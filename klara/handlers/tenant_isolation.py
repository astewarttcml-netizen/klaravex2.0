"""
Klaravex tenant isolation helpers — T8.10.

Two public helpers:

``scope_query(query, tenant_id)``
    Appends an ``AND client_email = $N`` (or ``AND tenant_id = $N``) clause to
    a raw SQL query string.  Returns ``(scoped_query, param_index)`` so the
    caller can extend the parameter list.

``verify_tenant_access(request_client_email, resource_client_email)``
    Raises ``HTTPException(403)`` if the two emails do not match (case-
    insensitive).  Call this before returning any resource to a client.

Docstring usage examples:
    >>> q, idx = scope_query("SELECT * FROM klaravex_tickets WHERE status = $1", "alice@example.com")
    >>> q
    'SELECT * FROM klaravex_tickets WHERE status = $1 AND client_email = $2'
    >>> idx
    2

    >>> verify_tenant_access("alice@example.com", "alice@example.com")   # no-op

    >>> # Raises HTTPException(403):
    >>> verify_tenant_access("alice@example.com", "bob@example.com")

SQL scoping example (asyncpg):
    pool = await get_pool()
    async with pool.acquire() as conn:
        query, idx = scope_query(
            "SELECT * FROM klaravex_kb_chunks WHERE chunk_index > $1",
            tenant_id="alice@example.com",
        )
        rows = await conn.fetch(query, 0, "alice@example.com")
"""

import re

from fastapi import HTTPException


def scope_query(query: str, tenant_id: str, column: str = "client_email") -> tuple[str, int]:
    """Append ``AND <column> = $N`` to a raw SQL query.

    Determines the next parameter index by counting existing ``$N`` placeholders
    in the query string.  Raises ``ValueError`` if *query* is empty or
    *tenant_id* is empty.

    Parameters
    ----------
    query:
        Raw SQL query, already containing at least a ``WHERE`` clause or no
        where clause (the caller is responsible for having a valid SQL fragment).
    tenant_id:
        The tenant identifier (usually ``client_email``) to scope to.
    column:
        The column name to scope on.  Defaults to ``client_email``.
        Pass ``"tenant_id"`` for tables that use a dedicated tenant column.

    Returns
    -------
    (scoped_query, next_param_index)
        ``scoped_query`` is the original query with the AND clause appended.
        ``next_param_index`` is the ``$N`` index used (so callers know where to
        append the tenant_id in their params list).

    Examples
    --------
    >>> q, idx = scope_query("SELECT * FROM klaravex_tickets WHERE status = $1", "alice@example.com")
    >>> q
    'SELECT * FROM klaravex_tickets WHERE status = $1 AND client_email = $2'
    >>> idx
    2

    >>> q2, idx2 = scope_query("SELECT * FROM klaravex_kb_chunks", "bob@example.com", column="tenant_id")
    >>> q2
    'SELECT * FROM klaravex_kb_chunks AND tenant_id = $1'
    >>> idx2
    1
    """
    if not query.strip():
        raise ValueError("scope_query: query must not be empty")
    if not tenant_id.strip():
        raise ValueError("scope_query: tenant_id must not be empty")

    # Count existing $N placeholders to find the next index.
    placeholders = re.findall(r"\$(\d+)", query)
    next_idx = max((int(n) for n in placeholders), default=0) + 1

    scoped = f"{query.rstrip()} AND {column} = ${next_idx}"
    return scoped, next_idx


def verify_tenant_access(
    request_client_email: str,
    resource_client_email: str,
) -> None:
    """Assert that *request_client_email* matches *resource_client_email*.

    Comparison is case-insensitive and strips leading/trailing whitespace.
    Raises ``HTTPException(403)`` on mismatch so the caller never needs to
    handle the bool — it either succeeds silently or raises.

    Parameters
    ----------
    request_client_email:
        The email from the authenticated request (e.g. from JWT claim or
        request body).
    resource_client_email:
        The email stored on the resource being accessed (e.g. ticket row's
        ``client_email`` column).

    Raises
    ------
    HTTPException(403):
        When the emails do not match.

    Examples
    --------
    >>> verify_tenant_access("Alice@Example.com", "alice@example.com")  # OK

    >>> verify_tenant_access("alice@example.com", "bob@example.com")
    Traceback (most recent call last):
        ...
    fastapi.exceptions.HTTPException: 403: tenant access denied
    """
    if request_client_email.strip().lower() != resource_client_email.strip().lower():
        raise HTTPException(
            status_code=403,
            detail="tenant access denied",
        )
