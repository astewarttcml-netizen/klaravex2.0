"""Embedding helper for semantic search (T-INF-09).

Calls an OpenAI-compatible ``/v1/embeddings`` endpoint. Defaults to the LiteLLM
proxy serving ``nomic-embed-text`` (768-dim), but every knob is env-configurable
so this works both on the rig (local proxy at localhost:8000) and wherever
klaravex-api is deployed (point EMBEDDING_BASE_URL at a reachable endpoint, e.g.
the rig over Tailscale, or a cloud embedding service).

Env:
  EMBEDDING_BASE_URL  default ``http://localhost:8000/v1``
  EMBEDDING_MODEL     default ``nomic-embed-text``
  EMBEDDING_API_KEY   bearer token for the endpoint (LiteLLM master key)
  EMBEDDING_DIM       default 768 (must match the migration's vector(N))
"""

import os

import httpx

EMBEDDING_BASE_URL = os.environ.get("EMBEDDING_BASE_URL", "http://localhost:8000/v1").rstrip("/")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
EMBEDDING_API_KEY = os.environ.get("EMBEDDING_API_KEY", "")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "768"))
# Optional forward proxy for the embedding call ONLY (not the whole app). Used when
# the embedder lives on the tailnet and the app reaches it via a Tailscale sidecar's
# local outbound proxy, e.g. EMBEDDING_PROXY=http://localhost:1055. Empty = direct.
EMBEDDING_PROXY = os.environ.get("EMBEDDING_PROXY", "")


class EmbeddingError(RuntimeError):
    """Raised when an embedding cannot be produced (network, shape, or empty input)."""


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if EMBEDDING_API_KEY:
        h["Authorization"] = f"Bearer {EMBEDDING_API_KEY}"
    return h


async def embed_text(text: str, *, timeout: float = 30.0) -> list[float]:
    """Return the embedding vector for ``text``. Raises EmbeddingError on failure."""
    text = (text or "").strip()
    if not text:
        raise EmbeddingError("cannot embed empty text")
    client_kwargs: dict = {"timeout": timeout}
    if EMBEDDING_PROXY:
        client_kwargs["proxy"] = EMBEDDING_PROXY
    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            resp = await client.post(
                f"{EMBEDDING_BASE_URL}/embeddings",
                headers=_headers(),
                json={"model": EMBEDDING_MODEL, "input": text},
            )
            resp.raise_for_status()
            vec = resp.json()["data"][0]["embedding"]
    except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError) as exc:
        raise EmbeddingError(f"embedding request failed: {exc}") from exc
    if len(vec) != EMBEDDING_DIM:
        raise EmbeddingError(f"expected {EMBEDDING_DIM}-dim embedding, got {len(vec)}")
    return [float(x) for x in vec]


def to_pgvector(vec: list[float]) -> str:
    """Format a float list as a pgvector text literal, e.g. ``[0.1,0.2,0.3]``.

    Passed to Postgres as text and cast with ``$1::vector`` — avoids requiring the
    optional ``pgvector`` Python package as a runtime dependency.
    """
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"
