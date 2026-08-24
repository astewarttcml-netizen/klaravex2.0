"""Per-session recording (spec §4 requirement 3 + §5).

Captures the full customer screen as H.264 video for the session duration.
Default sink directory is `.loki/remote-sessions/` (relative to the working
dir — infra/ when run via the worker containers); configurable via
$KLX_REMOTE_SESSION_VAULT for dev/test.

Pipeline:
    Frame (jpeg/rgb) → ffmpeg stdin (image2pipe / rawvideo) → H.264 mp4 on disk
    On close() the mp4 is encrypted in-place with AES-256-GCM using a key
    stored under .loki/remote-sessions/keys/<session_id>.key.

Data retention (US privacy policy):
    * Raw H.264 mp4 + per-session AES key: **30 days**, then both auto-purged
      by infra/cron/remote_session_purge.py. The DB row keeps a `recording_purged_at`
      timestamp so the audit chain stays defensible after deletion.
    * Derived data (action-event JSONL, transcripts): perpetual — feeds future
      fine-tunes, contains no frame content.
    * Retention period aligns with Klaravex's US privacy policy available at
      klaravex.com/privacy-policy.

Recording applies to all sessions. All customers are informed via the
privacy policy that sessions may be recorded for quality assurance and
incident review purposes.

H.264 encoding fallback:
    * If `ffmpeg` is not on PATH (CI / dev box without it), we fall back to
      raw JPEG frames on disk (one file per frame) so the recorder still has
      a usable artifact. The recording_format column in the DB tracks which
      mode was used so post-mortems aren't ambiguous.

G34.3 scaffold note: the encryption uses cryptography.AESGCM. If the
cryptography package is missing we plaintext-write and flag the row
`recording_encrypted=false` so it's obvious in the DB. Production deploy
MUST install cryptography>=42.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .protocol import Frame

log = logging.getLogger("klaravex.rustdesk.recording")

DEFAULT_VAULT_DIR = Path(os.environ.get(
    "KLX_REMOTE_SESSION_VAULT", ".loki/remote-sessions",
))
DEFAULT_KEY_DIR = Path(os.environ.get(
    "KLX_REMOTE_SESSION_KEY_DIR", DEFAULT_VAULT_DIR / "keys",
))
RETENTION_DAYS = int(os.environ.get("KLX_REMOTE_SESSION_RETENTION_DAYS", "30"))
TARGET_FPS = float(os.environ.get("KLX_RECORDING_FPS", "2"))  # spec §3: 1–2 fps


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


@dataclass
class SessionRecorder:
    """H.264 mp4 recorder with optional AES-256-GCM encryption at rest.

    Lifecycle:
        __post_init__         — create sink dir, spawn ffmpeg subprocess (or
                                fall back to JPEG-on-disk mode).
        write_frame(frame)    — push bytes into ffmpeg stdin (or write file).
        write_event(...)      — append a row to events.jsonl (derived data).
        close(outcome)        — close ffmpeg, encrypt resulting mp4, return
                                summary dict for the DB row.
    """

    session_id: str
    customer_email: str
    customer_region: str  # "us" | "other"
    sink_dir: Path | None = None  # if None, uses DEFAULT_VAULT_DIR/<session_id>
    frames_written: int = 0
    events_written: int = 0
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    enabled: bool = True

    # Internal state
    _mp4_path: Path | None = None
    _frames_fallback_dir: Path | None = None
    _ffmpeg: Any = None  # asyncio.subprocess.Process, late-bound to avoid type import
    _ffmpeg_mode: str = ""  # "h264" | "jpeg_fallback" | ""
    _aes_key: bytes = b""
    _closed: bool = False

    def __post_init__(self) -> None:
        # Resolve sink dir — default goes to the encrypted vault location.
        if self.sink_dir is None:
            self.sink_dir = DEFAULT_VAULT_DIR / self.session_id
        try:
            self.sink_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            # If the configured sink isn't writable (e.g. KLX_REMOTE_SESSION_VAULT
            # pointing at a root-owned dir), fall back to .loki/remote-sessions/.
            fallback = Path(".loki/remote-sessions") / self.session_id
            log.warning(
                "session %s: cannot write to %s — falling back to %s",
                self.session_id, self.sink_dir, fallback,
            )
            self.sink_dir = fallback
            self.sink_dir.mkdir(parents=True, exist_ok=True)

        # Open ffmpeg (or fall back). We launch the ffmpeg subprocess
        # eagerly so the first frame write doesn't pay the spawn latency,
        # but we tolerate ffmpeg missing entirely (CI).
        self._mp4_path = self.sink_dir / f"{self.session_id}.mp4"
        if _ffmpeg_available():
            try:
                self._spawn_ffmpeg_sync()
                self._ffmpeg_mode = "h264"
            except Exception as exc:  # noqa: BLE001
                log.warning("ffmpeg spawn failed (%s) — falling back to JPEG", exc)
                self._ffmpeg_mode = "jpeg_fallback"
        else:
            log.info("session %s: ffmpeg not on PATH — JPEG fallback mode", self.session_id)
            self._ffmpeg_mode = "jpeg_fallback"

        if self._ffmpeg_mode == "jpeg_fallback":
            self._frames_fallback_dir = self.sink_dir / "frames"
            self._frames_fallback_dir.mkdir(exist_ok=True)

        # Generate the AES-256 key now (32 bytes random), persist it to
        # the key dir so the retention purge worker can wipe key + payload
        # in one atomic step. Key file lives separately so it's easy to
        # delete the *key* (renders the mp4 unreadable) even if the
        # encrypted blob is still mid-purge.
        self._aes_key = secrets.token_bytes(32)
        try:
            DEFAULT_KEY_DIR.mkdir(parents=True, exist_ok=True)
            key_path = DEFAULT_KEY_DIR / f"{self.session_id}.key"
            key_path.write_bytes(self._aes_key)
            try:
                os.chmod(key_path, 0o600)
            except OSError:
                pass
        except PermissionError:
            # Dev mode — keep the key in the sink_dir so tests can clean up.
            key_path = self.sink_dir / "aes.key"
            key_path.write_bytes(self._aes_key)
            try:
                os.chmod(key_path, 0o600)
            except OSError:
                pass

    # ── ffmpeg pipe ─────────────────────────────────────────────────────────

    def _spawn_ffmpeg_sync(self) -> None:
        """Spawn ffmpeg reading JPEG frames from stdin, writing H.264 mp4.

        We use image2pipe input so we can pump heterogeneous frame sizes
        without re-spawning. -re is intentionally omitted (we're not realtime
        playback). The output is faststart so the mp4 is seekable mid-write.
        """
        import subprocess

        # NB: explicit `-vcodec mjpeg` on the input. Without it, recent
        # ffmpeg (>=7) refuses image2pipe with "Could not find codec
        # parameters for stream 0" because it can't probe a streaming
        # JPEG sequence. -vcodec tells it the codec up front.
        argv = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
            "-y",
            "-f", "image2pipe",
            "-vcodec", "mjpeg",
            "-framerate", str(TARGET_FPS),
            "-i", "-",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "veryfast",
            "-tune", "stillimage",
            "-movflags", "+faststart",
            str(self._mp4_path),
        ]
        self._ffmpeg = subprocess.Popen(  # noqa: S603 — argv is constructed locally
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    # ── Frame + event sinks ─────────────────────────────────────────────────

    def write_frame(self, frame: Frame) -> None:
        if not self.enabled or self._closed:
            return
        if self._ffmpeg_mode == "h264" and self._ffmpeg is not None:
            try:
                # Only jpeg-codec frames go directly into the ffmpeg pipe.
                # rgb/vp9/h264 frames pre-encode in protocol.py; we accept
                # all here and let ffmpeg's autodetect reject malformed ones.
                self._ffmpeg.stdin.write(frame.payload)
                self._ffmpeg.stdin.flush()
            except BrokenPipeError:
                # ffmpeg died — degrade to JPEG fallback mid-session so we
                # don't silently lose the rest of the recording.
                log.warning("ffmpeg pipe broken — switching to JPEG fallback")
                self._ffmpeg_mode = "jpeg_fallback"
                self._frames_fallback_dir = self.sink_dir / "frames"  # type: ignore[operator]
                self._frames_fallback_dir.mkdir(exist_ok=True)
                self._ffmpeg = None
        if self._ffmpeg_mode == "jpeg_fallback" and self._frames_fallback_dir is not None:
            path = self._frames_fallback_dir / f"{frame.sequence:06d}.jpg"
            path.write_bytes(frame.payload)
        self.frames_written += 1

    def write_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if not self.enabled or self._closed:
            return
        row = {
            "session_id": self.session_id,
            "event_type": event_type,
            "ts": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        with (self.sink_dir / "events.jsonl").open("a", encoding="utf-8") as f:  # type: ignore[operator]
            f.write(json.dumps(row) + "\n")
        self.events_written += 1

    # ── Close + encrypt ─────────────────────────────────────────────────────

    def close(self, outcome: str) -> dict[str, Any]:
        if self._closed:
            return self._summary(outcome, encrypted=False, size=0, purge_after=None)
        self._closed = True

        encrypted = False
        size_bytes = 0
        purge_after_iso: str | None = None
        final_path: Path | None = None

        if self.enabled:
            # Drain ffmpeg.
            if self._ffmpeg is not None:
                try:
                    if self._ffmpeg.stdin and not self._ffmpeg.stdin.closed:
                        self._ffmpeg.stdin.close()
                    self._ffmpeg.wait(timeout=10)
                except Exception as exc:  # noqa: BLE001
                    log.warning("ffmpeg close error: %s", exc)
                    try:
                        self._ffmpeg.kill()
                    except Exception:  # noqa: BLE001
                        pass

            final_path = self._mp4_path if self._ffmpeg_mode == "h264" else self._frames_fallback_dir

            # Encrypt the mp4 in place (the JPEG-fallback dir is left raw —
            # encrypting a directory of files in flight isn't worth the
            # complexity for the degraded code path).
            if self._ffmpeg_mode == "h264" and self._mp4_path is not None and self._mp4_path.exists():
                size_bytes = self._mp4_path.stat().st_size
                encrypted = self._encrypt_mp4_in_place(self._mp4_path)

            purge_after = datetime.now(timezone.utc) + timedelta(days=RETENTION_DAYS)
            purge_after_iso = purge_after.isoformat()

        summary = self._summary(
            outcome,
            encrypted=encrypted,
            size=size_bytes,
            purge_after=purge_after_iso,
        )
        try:
            (self.sink_dir / "summary.json").write_text(json.dumps(summary, indent=2))  # type: ignore[operator]
        except Exception:  # noqa: BLE001
            pass
        return summary

    def _encrypt_mp4_in_place(self, path: Path) -> bool:
        """AES-256-GCM encrypt the mp4. Writes <path>.enc, replaces original.

        Returns True iff encryption succeeded. False means the plaintext mp4
        remains — caller should set recording_encrypted=false in the DB so
        ops knows to handle it.
        """
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore
        except ImportError:
            log.warning("cryptography not installed — leaving %s plaintext", path)
            return False
        try:
            plaintext = path.read_bytes()
            nonce = secrets.token_bytes(12)
            ciphertext = AESGCM(self._aes_key).encrypt(nonce, plaintext, None)
            # Layout: 12-byte nonce || ciphertext (GCM tag is appended by
            # cryptography). 16-byte tag is part of `ciphertext`.
            enc_path = path.with_suffix(path.suffix + ".enc")
            enc_path.write_bytes(nonce + ciphertext)
            try:
                os.chmod(enc_path, 0o600)
            except OSError:
                pass
            # Replace plaintext with encrypted in-place so the DB recording_path
            # column always points to the encrypted-at-rest artifact.
            path.unlink()
            enc_path.rename(path)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("encrypt failed for %s: %s — leaving plaintext", path, exc)
            return False

    # ── Summary + helpers ───────────────────────────────────────────────────

    def _summary(
        self,
        outcome: str,
        *,
        encrypted: bool,
        size: int,
        purge_after: str | None,
    ) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "customer_email": self.customer_email,
            "customer_region": self.customer_region,
            "started_at": self.started_at,
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "frames_written": self.frames_written,
            "events_written": self.events_written,
            "outcome": outcome,
            "enabled": self.enabled,
            "recording_path": str(self._mp4_path) if self._mp4_path else None,
            "recording_format": self._ffmpeg_mode or "disabled",
            "recording_encrypted": encrypted,
            "recording_size_bytes": size,
            "recording_purge_after": purge_after,
        }


# ── Retention purge worker (called by infra/cron/remote_session_purge.py) ────


async def purge_expired_recordings(now: datetime | None = None) -> dict[str, int]:
    """Delete every recording (mp4 + AES key) whose retention window expired.

    Returns counts: {"scanned": N, "deleted": M, "errors": E}.
    Run from a cron — the worker itself is in infra/cron/ but the deletion
    logic lives here so the recorder owns both the write and the wipe path.
    """
    counts = {"scanned": 0, "deleted": 0, "errors": 0}
    try:
        from klara.handlers.lib.db import get_pool  # type: ignore
    except ImportError:
        log.warning("klara.handlers not importable — purge skipped")
        return counts
    now = now or datetime.now(timezone.utc)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT session_id, recording_path
              FROM klaravex_remote_sessions
             WHERE recording_path IS NOT NULL
               AND recording_purged_at IS NULL
               AND recording_purge_after < $1::timestamptz
            """,
            now,
        )
        for row in rows:
            counts["scanned"] += 1
            sid = row["session_id"]
            path = Path(row["recording_path"]) if row["recording_path"] else None
            try:
                if path and path.exists():
                    path.unlink()
                key_path = DEFAULT_KEY_DIR / f"{sid}.key"
                if key_path.exists():
                    key_path.unlink()
                await conn.execute(
                    "UPDATE klaravex_remote_sessions SET recording_purged_at=$1 WHERE session_id=$2",
                    now, sid,
                )
                counts["deleted"] += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("purge failed session=%s: %s", sid, exc)
                counts["errors"] += 1
    return counts
