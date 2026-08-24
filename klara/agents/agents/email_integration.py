"""
app/agents/email_integration.py
───────────────────────────────
Email Integration Builder (Agent 22 — MAIL)

Validates email delivery configuration, tests Resend connectivity, and
audits templates for compliance with the outreach domain policy.

Permission level: P2 (read + internal validation — no bulk sends)

Actions:
  health_check      — Ping Resend API, verify API key, inspect domain list
  validate_template — Check a template dict for required fields + risks
  test_send         — Send a single test email to verify end-to-end delivery

Blocked: unsanctioned bulk campaigns; cold email from main domain.
Fallback: disable sends and log failures.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

import aiohttp
import structlog

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel

logger = structlog.get_logger(__name__)

_RESEND_API = "https://api.resend.com"
_MAIN_DOMAIN = "klaravex.de"
_OUTREACH_SUBDOMAIN = "outreach.klaravex.de"

_REQUIRED_TEMPLATE_KEYS = {"to", "subject", "html_body"}


class EmailIntegrationAgent(BaseAgent):
    """
    Email delivery health and configuration agent.

    Validates Resend API connectivity, sender domain setup, and template
    completeness. Does NOT send bulk campaigns. Cold outreach must use
    outreach.klaravex.de only.

    Actions:
      health_check      — Ping Resend API, verify API key, check domain list
      validate_template — Check template dict for required fields + policy risks
      test_send         — Send a single test email (verifies end-to-end delivery)
    """

    name = "email_integration"
    description = (
        "Email delivery health, configuration validation, and Resend provider "
        "integration. Validates API keys, domain setup, and templates."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        action = input_data.get("action", "health_check")
        log.info("email_integration.start", action=action)

        if action == "health_check":
            return await self._health_check(log)
        elif action == "validate_template":
            template = input_data.get("template", {})
            return self._validate_template(template, log)
        elif action == "test_send":
            test_email = input_data.get("test_email", "")
            return await self._test_send(test_email, log)
        else:
            return AgentResult.fail(
                f"Unknown action '{action}'. "
                "Valid: health_check, validate_template, test_send"
            )

    # ── Actions ───────────────────────────────────────────────────────────────

    async def _health_check(self, log) -> AgentResult:
        """Verify Resend API key and domain configuration."""
        api_key = os.getenv("RESEND_API_KEY", "").strip()
        from_addr = os.getenv("FROM_EMAIL", "").strip()
        approval_email = os.getenv("APPROVAL_NOTIFY_EMAIL", "").strip()

        issues: list[str] = []
        details: dict = {}

        # API key
        if not api_key:
            issues.append("RESEND_API_KEY is not set")
            details["api_key"] = "missing"
        else:
            details["api_key"] = f"set ({api_key[:5]}{'*' * 16})"

        # FROM_EMAIL
        if not from_addr:
            issues.append("FROM_EMAIL is not set")
            details["from_email"] = "missing"
        else:
            details["from_email"] = from_addr
            if (
                from_addr.endswith(f"@{_MAIN_DOMAIN}")
                and "outreach" not in from_addr
            ):
                issues.append(
                    f"FROM_EMAIL uses main domain @{_MAIN_DOMAIN} — "
                    f"cold outreach must use @{_OUTREACH_SUBDOMAIN}"
                )

        details["approval_notify_email"] = approval_email or "not set"

        # Live Resend API ping
        if api_key:
            api_status = await self._ping_resend(api_key)
            details["resend_api"] = api_status
            if api_status.get("error"):
                issues.append(f"Resend API: {api_status['error']}")
        else:
            details["resend_api"] = {"reachable": False, "reason": "no api key"}

        status = "healthy" if not issues else (
            "degraded" if len(issues) < 3 else "error"
        )

        log.info(
            "email_integration.health_check",
            status=status,
            issue_count=len(issues),
        )

        return AgentResult.ok(
            output={
                "status": status,
                "issues": issues,
                "details": details,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def _validate_template(self, template: dict, log) -> AgentResult:
        """Check a template dict for required fields and policy risks."""
        missing = list(_REQUIRED_TEMPLATE_KEYS - set(template.keys()))
        warnings: list[str] = []

        # Bulk send detection
        to_field = template.get("to", "")
        if isinstance(to_field, list) and len(to_field) > 5:
            warnings.append(
                f"'to' has {len(to_field)} recipients — bulk sends require "
                "approval and must use the outreach subdomain"
            )

        # Domain compliance
        from_field = str(template.get("from", ""))
        if (
            from_field
            and _MAIN_DOMAIN in from_field
            and "outreach" not in from_field
        ):
            warnings.append(
                f"'from' uses main domain {_MAIN_DOMAIN} — cold outreach must "
                f"use {_OUTREACH_SUBDOMAIN}"
            )

        # Subject length
        subject = str(template.get("subject", ""))
        if len(subject) > 78:
            warnings.append(
                f"Subject line is {len(subject)} chars — keep under 78 for "
                "deliverability"
            )

        # Unsubscribe check for outreach templates
        html = str(template.get("html_body", template.get("html", "")))
        if "outreach" in from_field and "unsubscribe" not in html.lower():
            warnings.append(
                "Cold outreach template missing unsubscribe link — "
                "required by CAN-SPAM / GDPR"
            )

        valid = not missing and not any(
            w for w in warnings if "bulk" in w or "main domain" in w
        )

        log.info(
            "email_integration.template_validated",
            missing=missing,
            warnings=warnings,
            valid=valid,
        )

        return AgentResult.ok(
            output={
                "valid": valid,
                "missing_fields": missing,
                "warnings": warnings,
                "template_keys": list(template.keys()),
            }
        )

    async def _test_send(self, test_email: str, log) -> AgentResult:
        """Send a single test email via Resend to verify end-to-end delivery."""
        if not test_email or not re.match(r"[^@]+@[^@]+\.[^@]+", test_email):
            return AgentResult.fail("Valid 'test_email' address is required.")

        api_key = os.getenv("RESEND_API_KEY", "").strip()
        from_addr = os.getenv("FROM_EMAIL", f"noreply@{_MAIN_DOMAIN}")

        if not api_key:
            return AgentResult.fail("RESEND_API_KEY is not configured.")

        payload = {
            "from": from_addr,
            "to": [test_email],
            "subject": "[Klara AI] Email integration test",
            "html": (
                "<p>This is an automated test from the Klara AI "
                "Email Integration Builder.</p>"
                "<p>If you received this, transactional email delivery "
                "is working correctly.</p>"
                f"<p><small>Sent: {datetime.now(timezone.utc).isoformat()} UTC</small></p>"
            ),
        }

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            ) as session:
                async with session.post(
                    f"{_RESEND_API}/emails",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                ) as resp:
                    body = await resp.json()
                    if resp.status in (200, 201):
                        log.info(
                            "email_integration.test_send_ok",
                            email_id=body.get("id"),
                            to=test_email,
                        )
                        return AgentResult.ok(
                            output={
                                "sent": True,
                                "to": test_email,
                                "resend_id": body.get("id"),
                                "sent_at": datetime.now(timezone.utc).isoformat(),
                            }
                        )
                    else:
                        error = body.get("message", str(body))
                        log.error(
                            "email_integration.test_send_failed",
                            status=resp.status,
                            error=error,
                        )
                        return AgentResult.fail(
                            f"Resend API returned {resp.status}: {error}"
                        )
        except Exception as exc:
            log.error("email_integration.test_send_error", error=str(exc))
            return AgentResult.fail(f"Email send failed: {exc}")

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _ping_resend(self, api_key: str) -> dict:
        """Ping Resend /domains to verify API key validity."""
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            ) as session:
                async with session.get(
                    f"{_RESEND_API}/domains",
                    headers={"Authorization": f"Bearer {api_key}"},
                ) as resp:
                    if resp.status == 200:
                        body = await resp.json()
                        domains = [
                            d.get("name") for d in body.get("data", [])
                        ]
                        return {"reachable": True, "domains": domains}
                    elif resp.status == 401:
                        return {
                            "reachable": True,
                            "error": "Invalid API key (401)",
                        }
                    else:
                        return {
                            "reachable": True,
                            "error": f"Unexpected status {resp.status}",
                        }
        except Exception as exc:
            return {"reachable": False, "error": str(exc)}
