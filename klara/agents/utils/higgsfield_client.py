"""
app/utils/higgsfield_client.py
──────────────────────────────
Async Higgsfield AI client for social media image generation.

Provides a single public coroutine:

    generate_instagram_image(prompt, settings) -> str

This generates a Soul-character still image sized for an Instagram feed post
(4:5 portrait), downloads it, saves it to the nginx-served static directory
on disk, and returns the public HTTPS URL for use in the Instagram Graph API.

Architecture notes:
  - All HTTP is async (httpx.AsyncClient) — no blocking calls.
  - Image saved to settings.portal_files_base_path/../static/ig/<slug>.jpg,
    which nginx serves at settings.instagram_image_base_url/<slug>.jpg.
  - Polling uses exponential backoff with a hard timeout (default 180 s).
  - On failure, raises HiggsFieldError — caller should fall back gracefully.

Requires: httpx (already a transitive dep via httpcore in FastAPI stack).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx
import structlog

from klara.rarv.runtime import Settings

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://api.higgsfield.ai"
_GENERATE_ENDPOINT = "/v1/generation/soul"
_STATUS_ENDPOINT = "/v1/generation/{job_id}"

# Polling parameters
_POLL_INITIAL_SLEEP = 4.0     # seconds before first status check
_POLL_BACKOFF_FACTOR = 1.4    # multiply sleep by this each retry
_POLL_MAX_SLEEP = 20.0        # cap per-poll sleep
_POLL_TIMEOUT = 180.0         # hard timeout seconds

# Where nginx serves static images from (must match nginx config)
# Layout on Hetzner:   /opt/loki-agents/static/ig/<slug>.jpg
#                      ↕
# Public URL:          https://api.klaravex.de/static/ig/<slug>.jpg
_STATIC_IG_DIR_DEFAULT = "/opt/loki-agents/static/ig"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class HiggsFieldError(RuntimeError):
    """Raised when the Higgsfield API returns an unexpected error or times out."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _static_ig_dir(settings: Settings) -> Path:
    """
    Resolve the on-disk directory where IG images are saved.

    Uses the directory portion of instagram_image_base_url mapped back to the
    filesystem via the known nginx root.  Falls back to a sane default so the
    function works in dev when the Hetzner path doesn't exist locally.
    """
    # In production this path must exist and be writable by the `app` user.
    # In dev, writes are skipped (see generate_instagram_image logic).
    return Path(_STATIC_IG_DIR_DEFAULT)


def _public_url(settings: Settings, filename: str) -> str:
    """Convert a local filename to its public HTTPS URL."""
    base = settings.instagram_image_base_url.rstrip("/")
    return f"{base}/{filename}"


async def _submit_job(
    prompt: str,
    settings: Settings,
    client: httpx.AsyncClient,
) -> str:
    """
    POST to Higgsfield to create a Soul image generation job.

    Returns the job_id (string UUID).
    """
    payload = {
        "soul_id": settings.higgsfield_soul_id,
        "model": settings.higgsfield_image_model,
        "prompt": prompt,
        "aspect_ratio": settings.higgsfield_instagram_aspect,
        # Disable preset recommendations — we want literal generation.
        "declined_preset_id": None,
    }

    log = logger.bind(action="higgsfield_submit", model=settings.higgsfield_image_model)
    log.info("Submitting Higgsfield image generation job", prompt_preview=prompt[:80])

    resp = await client.post(
        f"{_BASE_URL}{_GENERATE_ENDPOINT}",
        json=payload,
        headers={
            "Authorization": f"Bearer {settings.higgsfield_api_key}",
            "Content-Type": "application/json",
        },
    )

    if resp.status_code not in (200, 201, 202):
        raise HiggsFieldError(
            f"Higgsfield submit failed: HTTP {resp.status_code} — {resp.text[:300]}"
        )

    data = resp.json()
    job_id = data.get("id") or data.get("job_id") or data.get("generation_id")
    if not job_id:
        raise HiggsFieldError(
            f"Higgsfield submit response missing job id: {data}"
        )

    log.info("Higgsfield job submitted", job_id=job_id)
    return str(job_id)


async def _poll_job(
    job_id: str,
    settings: Settings,
    client: httpx.AsyncClient,
) -> str:
    """
    Poll Higgsfield until the job completes.

    Returns the CDN URL of the generated image (string).
    Raises HiggsFieldError on failure or timeout.
    """
    log = logger.bind(action="higgsfield_poll", job_id=job_id)
    endpoint = f"{_BASE_URL}{_STATUS_ENDPOINT.format(job_id=job_id)}"
    headers = {"Authorization": f"Bearer {settings.higgsfield_api_key}"}

    sleep = _POLL_INITIAL_SLEEP
    deadline = time.monotonic() + _POLL_TIMEOUT

    while True:
        if time.monotonic() > deadline:
            raise HiggsFieldError(
                f"Higgsfield job {job_id} timed out after {_POLL_TIMEOUT}s"
            )

        await asyncio.sleep(sleep)
        sleep = min(sleep * _POLL_BACKOFF_FACTOR, _POLL_MAX_SLEEP)

        resp = await client.get(endpoint, headers=headers)
        if resp.status_code != 200:
            log.warning(
                "Higgsfield poll non-200",
                status=resp.status_code,
                body=resp.text[:200],
            )
            continue

        data = resp.json()
        status = (data.get("status") or "").upper()

        log.debug("Higgsfield poll", status=status)

        if status in ("COMPLETED", "SUCCEEDED", "DONE", "SUCCESS"):
            # Extract image URL — field name varies by model type
            image_url = (
                data.get("image_url")
                or data.get("output_url")
                or data.get("result_url")
                or (data.get("outputs") or [None])[0]
                or (data.get("results") or [None])[0]
            )
            if not image_url:
                raise HiggsFieldError(
                    f"Higgsfield job {job_id} completed but no image URL found: {data}"
                )
            log.info("Higgsfield generation complete", image_url=image_url)
            return str(image_url)

        if status in ("FAILED", "ERROR", "CANCELLED"):
            error_msg = data.get("error") or data.get("message") or status
            raise HiggsFieldError(
                f"Higgsfield job {job_id} failed: {error_msg}"
            )

        # Still PENDING / RUNNING / QUEUED — keep polling


async def _download_image(
    cdn_url: str,
    dest_path: Path,
    client: httpx.AsyncClient,
) -> None:
    """Download the generated image from CDN and write it to dest_path."""
    log = logger.bind(action="higgsfield_download", dest=str(dest_path))
    log.info("Downloading Higgsfield image", cdn_url=cdn_url)

    async with client.stream("GET", cdn_url) as resp:
        resp.raise_for_status()
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as fh:
            async for chunk in resp.aiter_bytes(chunk_size=65536):
                fh.write(chunk)

    log.info("Image saved", size_bytes=dest_path.stat().st_size)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_instagram_image(
    prompt: str,
    settings: Settings,
    slug: Optional[str] = None,
) -> str:
    """
    Generate a Soul-character image sized for an Instagram feed post.

    Workflow:
      1. POST job to Higgsfield (soul_cinematic, 4:5 aspect ratio)
      2. Poll until COMPLETED
      3. Download image from CloudFront CDN
      4. Save to /opt/loki-agents/static/ig/<slug>.jpg on the filesystem
      5. Return public URL: https://api.klaravex.de/static/ig/<slug>.jpg

    Args:
        prompt:   Visual description for the image (derived from post caption).
        settings: Klara AI Settings singleton.
        slug:     Optional filename stem.  Defaults to a short UUID.

    Returns:
        Public HTTPS URL of the saved image.

    Raises:
        HiggsFieldError: Any API, timeout, or download failure.
        RuntimeError: higgsfield_configured is False — caller should guard.
    """
    if not settings.higgsfield_configured:
        raise RuntimeError(
            "Higgsfield is not configured — set HIGGSFIELD_API_KEY in .env"
        )

    if not slug:
        slug = f"ig_{uuid.uuid4().hex[:12]}"

    filename = f"{slug}.jpg"
    static_dir = _static_ig_dir(settings)
    dest_path = static_dir / filename

    log = logger.bind(
        action="generate_instagram_image",
        slug=slug,
        soul_id=settings.higgsfield_soul_id,
        model=settings.higgsfield_image_model,
        aspect=settings.higgsfield_instagram_aspect,
    )

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        # Step 1: Submit
        job_id = await _submit_job(prompt, settings, client)

        # Step 2: Poll
        cdn_url = await _poll_job(job_id, settings, client)

        # Step 3 & 4: Download and save
        # In development the static dir may not exist — skip write and return
        # the raw CDN URL instead (Instagram requires a public URL anyway;
        # the CDN URL works as long as Instagram fetches it before it expires).
        if static_dir.exists():
            await _download_image(cdn_url, dest_path, client)
            public_url = _public_url(settings, filename)
        else:
            log.warning(
                "Static IG dir does not exist — using CDN URL directly (dev mode)",
                static_dir=str(static_dir),
                cdn_url=cdn_url,
            )
            public_url = cdn_url

    log.info("Instagram image ready", public_url=public_url)
    return public_url


async def generate_instagram_image_from_caption(
    caption: str,
    settings: Settings,
    slug: Optional[str] = None,
) -> str:
    """
    Convenience wrapper: derives a visual prompt from a post caption and calls
    generate_instagram_image().

    The prompt instructs Higgsfield to create a scene that complements the
    caption's topic — Klaravex brand context is baked in so the
    character and setting are consistent.

    Args:
        caption:  The full Instagram post caption text.
        settings: Klara AI Settings singleton.
        slug:     Optional filename stem for the saved image.

    Returns:
        Public HTTPS URL.
    """
    # Derive a focused prompt from the caption.
    # Keep it under ~200 chars to stay well inside Higgsfield's prompt limit.
    # The IT Guy character + Berlin office environment is always anchored.
    caption_preview = caption[:300].strip()

    prompt = (
        "IT professional, modern Berlin office, cinematic lighting, "
        "professional and authoritative expression, crisp suit or smart-casual, "
        f"scene matching the theme: {caption_preview}"
    )

    return await generate_instagram_image(prompt=prompt, settings=settings, slug=slug)
