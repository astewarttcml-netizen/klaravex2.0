"""
klaravex/infra/klara.handlers/lib/higgsfield_client.py
─────────────────────────────────────────────────────
Higgsfield image-generation client. Generates branded images for Instagram
captions (and any other platform that benefits from a visual).

Ported from itexperts-berlin/loki-agents/app/utils/higgsfield_client.py
on 2026-06-26.

Klaravex adaptations:
  - structlog → stdlib logging
  - klara.rarv.runtime.Settings → in-file _Settings shim reading os.environ
  - Static asset path defaults to /tmp/klaravex_ig if not configured

Required env vars:
  HIGGSFIELD_API_KEY            (required)
  HIGGSFIELD_PROJECT_ID         (optional)
  HIGGSFIELD_MODEL              (optional, defaults to higgsfield's default)
  HIGGSFIELD_POLL_INTERVAL_S    (optional, default 3)
  HIGGSFIELD_POLL_TIMEOUT_S     (optional, default 180)
  IG_IMAGE_STATIC_DIR           (optional, default /tmp/klaravex_ig)
  IG_IMAGE_PUBLIC_BASE_URL      (optional, e.g. https://api.klaravex.com/static/ig)
"""


import asyncio
import hashlib
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger("klaravex.higgsfield_client")


class _StructLogShim:
    def __init__(self, base, ctx=None):
        self._log = base
        self._ctx: dict = ctx or {}

    def bind(self, **kw) -> "_StructLogShim":
        return _StructLogShim(self._log, {**self._ctx, **kw})

    def _fmt(self, kw: dict) -> dict:
        return {**self._ctx, **kw}

    def debug(self, event, **kw): self._log.debug("%s %s", event, self._fmt(kw) or "")
    def info(self, event, **kw): self._log.info("%s %s", event, self._fmt(kw) or "")
    def warning(self, event, **kw): self._log.warning("%s %s", event, self._fmt(kw) or "")
    def error(self, event, **kw): self._log.error("%s %s", event, self._fmt(kw) or "")
    def exception(self, event, **kw): self._log.exception("%s %s", event, self._fmt(kw) or "")

logger = _StructLogShim(log)


class _Settings:
    @property
    def higgsfield_api_key(self): return os.environ.get("HIGGSFIELD_API_KEY", "")
    @property
    def higgsfield_project_id(self): return os.environ.get("HIGGSFIELD_PROJECT_ID", "")
    @property
    def higgsfield_model(self): return os.environ.get("HIGGSFIELD_MODEL", "")
    @property
    def higgsfield_poll_interval_s(self):
        try: return int(os.environ.get("HIGGSFIELD_POLL_INTERVAL_S", "3"))
        except: return 3
    @property
    def higgsfield_poll_timeout_s(self):
        try: return int(os.environ.get("HIGGSFIELD_POLL_TIMEOUT_S", "180"))
        except: return 180
    @property
    def ig_image_static_dir(self): return os.environ.get("IG_IMAGE_STATIC_DIR", "/tmp/klaravex_ig")
    @property
    def ig_image_public_base_url(self): return os.environ.get("IG_IMAGE_PUBLIC_BASE_URL", "")
    @property
    def higgsfield_instagram_aspect(self): return os.environ.get("HIGGSFIELD_INSTAGRAM_ASPECT", "4:5")
    @property
    def higgsfield_soul_id(self): return os.environ.get("HIGGSFIELD_SOUL_ID", "")
    @property
    def higgsfield_image_model(self): return os.environ.get("HIGGSFIELD_MODEL", "soul_cinematic")
    @property
    def higgsfield_configured(self): return bool(os.environ.get("HIGGSFIELD_API_KEY", ""))

settings = _Settings()

# ---------------------------------------------------------------------------
# Higgsfield API constants (override via env for testing)
# ---------------------------------------------------------------------------
def _base_url() -> str:
    # Read at call time so monkeypatch.setenv("HIGGSFIELD_BASE_URL", …) takes effect in tests.
    return os.environ.get("HIGGSFIELD_BASE_URL", "https://api.higgsfield.ai")
_GENERATE_ENDPOINT = "/v1/images/generations"
_STATUS_ENDPOINT = "/v1/images/generations/{job_id}"
_POLL_INITIAL_SLEEP = 3       # seconds before first poll
_POLL_BACKOFF_FACTOR = 1.5    # multiplicative sleep growth per poll
_POLL_MAX_SLEEP = 30          # seconds — cap per poll interval
_POLL_TIMEOUT = 180           # total seconds before HiggsFieldError


class HiggsFieldError(RuntimeError):
    """Raised when the Higgsfield API returns an unexpected error or times out."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _static_ig_dir(settings: _Settings) -> Path:
    """Resolve the on-disk directory where IG images are saved."""
    return Path(settings.ig_image_static_dir)


def _public_url(settings: _Settings, filename: str) -> str:
    """Convert a local filename to its public HTTPS URL."""
    base = settings.ig_image_public_base_url.rstrip("/")
    return f"{base}/{filename}"


async def _submit_job(
    prompt: str,
    settings: _Settings,
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
        f"{_base_url()}{_GENERATE_ENDPOINT}",
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
    settings: _Settings,
    client: httpx.AsyncClient,
) -> str:
    """
    Poll Higgsfield until the job completes.

    Returns the CDN URL of the generated image (string).
    Raises HiggsFieldError on failure or timeout.
    """
    log = logger.bind(action="higgsfield_poll", job_id=job_id)
    endpoint = f"{_base_url()}{_STATUS_ENDPOINT.format(job_id=job_id)}"
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
# Azure Blob upload (SEC5)
# ---------------------------------------------------------------------------

def _ig_blob_sas() -> str:
    return os.environ.get("AZURE_IG_BLOB_SAS", "").lstrip("?")


def _ig_blob_base() -> str:
    return os.environ.get(
        "AZURE_IG_BLOB_BASE",
        "https://klxhelperfiles.blob.core.windows.net/ig-static",
    ).rstrip("/")


async def _upload_to_blob(dest_path: Path, client: httpx.AsyncClient) -> None:
    """PUT the generated file into the public-read ig-static blob container.

    The stateless `klaravex-api` container 302-redirects `/static/ig/<name>` to
    this blob, so Instagram's Graph API can fetch a permanent public HTTPS URL.
    No-op (log only) when AZURE_IG_BLOB_SAS is unset — dev/deploy configs that
    still serve locally keep working.
    """
    sas = _ig_blob_sas()
    if not sas:
        log.info(
            "AZURE_IG_BLOB_SAS not set — skipping blob upload",
            dest=str(dest_path),
        )
        return
    with open(dest_path, "rb") as fh:
        data = fh.read()
    url = f"{_ig_blob_base()}/{dest_path.name}?{sas}"
    resp = await client.put(
        url,
        content=data,
        headers={"Content-Type": "image/jpeg", "x-ms-blob-type": "BlockBlob"},
    )
    if resp.status_code not in (200, 201):
        raise HiggsFieldError(
            f"blob upload failed: HTTP {resp.status_code} — {resp.text[:300]}"
        )
    log.info("Image uploaded to blob", blob=dest_path.name, size_bytes=len(data))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_instagram_image(
    prompt: str,
    settings: _Settings,
    slug: Optional[str] = None,
) -> str:
    """
    Generate a Soul-character image sized for an Instagram feed post.

    Workflow:
      1. POST job to Higgsfield (soul_cinematic, 4:5 aspect ratio)
      2. Poll until COMPLETED
      3. Download image from CloudFront CDN
      4. Save to /opt/loki-agents/static/ig/<slug>.jpg on the filesystem
      5. Return public URL: https://api.klaravex.com/static/ig/<slug>.jpg

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
            # SEC5: PUT to the public-read ig-static blob so the stateless
            # api container can 302-redirect to it (IG needs a permanent URL).
            await _upload_to_blob(dest_path, client)
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


import re as _re


def _caption_to_scene(caption: str) -> str:
    """Sanitize a post caption into a safe Higgsfield prompt fragment.

    Strips URLs, hashtags, mentions, and non-ASCII (emojis) that Higgsfield
    may try to render literally — which risks brand-inconsistent imagery or
    unwanted logo/text artifacts in the generated frame. (T14.7 QA-1)
    """
    text = _re.sub(r"https?://\S+", "", caption)
    text = _re.sub(r"[#@]\S+", "", text)
    text = _re.sub(r"[^\x00-\x7F]", "", text)
    text = " ".join(text.split())[:120]
    return text or "technology and cybersecurity consulting"


async def generate_instagram_image_from_caption(
    caption: str,
    settings: _Settings,
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
    # Warn early if soul_id is unset — each generation will produce a
    # different character, breaking feed visual continuity. (T14.7 QA-4)
    if not getattr(settings, "higgsfield_soul_id", None):
        log.warning(
            "HIGGSFIELD_SOUL_ID not set — character will vary per generation "
            "(visual continuity risk; set env var to pin the soul)"
        )

    scene = _caption_to_scene(caption)

    # Improved prompt: anchors palette, suppresses text artifacts, caps
    # scene descriptor at sanitized 120 chars. (T14.7 QA-2)
    prompt = (
        "Portrait of an IT security professional, clean modern office environment, "
        "cinematic side lighting, confident composed expression, "
        "business casual attire, shallow depth of field, "
        "dark navy and slate color tones, "
        "no text visible in image, no screen glare, "
        f"subject engaged with: {scene}"
    )

    return await generate_instagram_image(prompt=prompt, settings=settings, slug=slug)
