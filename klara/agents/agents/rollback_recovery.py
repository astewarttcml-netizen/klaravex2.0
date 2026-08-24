"""
app/agents/rollback_recovery.py
────────────────────────────────
Rollback/Recovery Builder (Agent 25 — ROLL)

Generates rollback playbooks, captures system snapshots, and coordinates
incident recovery for the Klara AI backend.

Permission level: P2 (read + internal write — no deployment execution)

Actions:
  snapshot  — Capture system state: DB row counts, agent count, migration head
  playbook  — Return a structured rollback runbook for a named incident type
  verify    — Post-recovery health check: DB, alembic head, agent registry

Blocked: blind rollback without scope confirmation.
Fallback: stop and request explicit incident approval before any destructive
action. Always snapshot before and after recovery.
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select, text

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel
from klara.rarv.audit import AuditLog
from klara.rarv.lead import Lead

logger = structlog.get_logger(__name__)

_INCIDENT_TYPES = [
    "migration_failed",
    "container_restart_loop",
    "db_connection_lost",
    "agent_import_error",
    "env_drift",
    "general",
]


class RollbackRecoveryAgent(BaseAgent):
    """
    Incident recovery coordinator and system snapshot agent.

    Captures point-in-time state, produces structured rollback playbooks
    for named incident types, and verifies system health post-recovery.
    Does NOT execute deployment commands directly — produces runbooks for
    human or operator execution.
    """

    name = "rollback_recovery"
    description = (
        "Captures system snapshots, generates structured rollback playbooks "
        "for named incidents, and verifies system health post-recovery."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        action = input_data.get("action", "snapshot")
        log.info("rollback_recovery.start", action=action)

        if action == "snapshot":
            return await self._snapshot(context, log)
        elif action == "playbook":
            incident = input_data.get("incident_type", "general")
            return self._playbook(incident, log)
        elif action == "verify":
            return await self._verify(context, log)
        else:
            return AgentResult.fail(
                f"Unknown action '{action}'. "
                "Valid: snapshot, playbook, verify"
            )

    # ── Snapshot ──────────────────────────────────────────────────────────────

    async def _snapshot(self, context: AgentContext, log) -> AgentResult:
        """Capture current system state."""
        db = context.db
        snap: dict = {}
        now = datetime.now(timezone.utc).isoformat()

        # Lead counts by status
        try:
            lead_q = await db.execute(
                select(Lead.status, func.count()).group_by(Lead.status)
            )
            snap["leads_by_status"] = dict(lead_q.all())
            snap["leads_total"] = sum(snap["leads_by_status"].values())
        except Exception as exc:
            snap["leads_by_status"] = {}
            snap["leads_total"] = f"error: {exc}"

        # Audit log count
        try:
            audit_q = await db.execute(
                select(func.count()).select_from(AuditLog)
            )
            snap["audit_log_entries"] = audit_q.scalar() or 0
        except Exception as exc:
            snap["audit_log_entries"] = f"error: {exc}"

        # Alembic migration head
        try:
            head_q = await db.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            )
            row = head_q.fetchone()
            snap["migration_head"] = row[0] if row else "unknown"
        except Exception as exc:
            snap["migration_head"] = f"error: {exc}"

        # Registered agent count
        try:
            from app.agents.registry import registry
            agents = registry.all()
            snap["registered_agents"] = len(agents)
            snap["agent_names"] = [a.name for a in agents]
        except Exception as exc:
            snap["registered_agents"] = f"error: {exc}"
            snap["agent_names"] = []

        log.info(
            "rollback_recovery.snapshot_complete",
            leads_total=snap.get("leads_total"),
            migration_head=snap.get("migration_head"),
            agents=snap.get("registered_agents"),
        )

        return AgentResult.ok(output={"snapshot": snap, "captured_at": now})

    # ── Playbook ──────────────────────────────────────────────────────────────

    def _playbook(self, incident_type: str, log) -> AgentResult:
        """Return structured rollback runbook for a named incident."""
        playbooks: dict[str, dict] = {
            "migration_failed": {
                "title": "Rollback: Failed Alembic Migration",
                "severity": "HIGH",
                "steps": [
                    "1. SSH: ssh root@49.13.37.100",
                    "2. Check logs: docker logs loki_api 2>&1 | grep -i 'alembic\\|error' | tail -40",
                    "3. Current head: cd /opt/loki-agents && docker compose exec api alembic current",
                    "4. Downgrade: docker compose exec api alembic downgrade -1",
                    "5. Verify: docker compose exec api alembic current",
                    "6. Fix migration file in /opt/loki-agents/migrations/versions/",
                    "7. SCP fixed file — Dockerfile COPY picks it up on rebuild",
                    "8. Rebuild: docker compose build api && docker compose up -d api",
                    "9. Run rollback_recovery verify to confirm health",
                ],
                "critical_note": (
                    "/root/loki-agents/.env is source of truth — restore "
                    "/opt/loki-agents/.env from it if drifted"
                ),
                "escalate_if": (
                    "Downgrade fails or DB tables are in inconsistent state"
                ),
            },
            "container_restart_loop": {
                "title": "Rollback: Docker Container Crash Loop",
                "severity": "HIGH",
                "steps": [
                    "1. Identify crashing container: docker compose ps",
                    "2. Read crash: docker logs loki_api --tail 100 (or loki_worker / loki_beat)",
                    "3. If ImportError: check for missing .py file or syntax error in new agent",
                    "4. Disable bad agent: mv /opt/loki-agents/app/agents/AGENT.py{,.disabled}",
                    "5. Remove import from registry.py",
                    "6. Rebuild: docker compose build api && docker compose up -d",
                    "7. Verify: docker compose exec api python -c 'from app.agents.registry import registry; print(len(registry.all()))'",
                    "8. If DB issue: verify DATABASE_URL points to Cloud86 not @db:5432",
                    "9. If Redis issue: docker compose restart redis",
                ],
                "critical_note": (
                    "Never edit /opt/loki-agents/.env directly — "
                    "copy from /root/loki-agents/.env"
                ),
                "escalate_if": (
                    "Container still crashes after .env restore and image rebuild"
                ),
            },
            "db_connection_lost": {
                "title": "Rollback: Cloud86 PostgreSQL Unreachable",
                "severity": "CRITICAL",
                "steps": [
                    "1. Test from Hetzner: nc -zv lend.your-database.de 5432",
                    "2. Check DATABASE_URL: grep DATABASE_URL /opt/loki-agents/.env",
                    "3. If URL shows @db:5432 → DRIFTED. Restore from /root/loki-agents/.env",
                    "4. Restore: cp /root/loki-agents/.env /opt/loki-agents/.env",
                    "5. Restart: docker compose down && docker compose up -d",
                    "6. Verify with real DB-touching endpoint (not /health)",
                    "7. If Cloud86 is genuinely down: check status page, alert Anthony",
                ],
                "critical_note": (
                    "@db:5432 = WRONG (local Docker); "
                    "@lend.your-database.de:5432 = CORRECT (Cloud86)"
                ),
                "escalate_if": (
                    "Cloud86 confirms outage — escalate for business continuity decision"
                ),
            },
            "agent_import_error": {
                "title": "Rollback: Agent Import Failure on Startup",
                "severity": "MEDIUM",
                "steps": [
                    "1. Check startup: docker logs loki_api 2>&1 | grep -i 'import\\|traceback' | head -50",
                    "2. Identify failing module from traceback",
                    "3. Disable: mv /opt/loki-agents/app/agents/AGENT.py{,.disabled}",
                    "4. Remove import + registration from registry.py",
                    "5. Rebuild: docker compose build api && docker compose up -d api",
                    "6. Verify: docker compose exec api python -c 'from app.agents.registry import registry; print(len(registry.all()))'",
                    "7. Fix the agent and re-enable after local testing",
                ],
                "critical_note": (
                    "Always verify registry.py imports match existing .py files"
                ),
                "escalate_if": (
                    "Multiple agents failing — may indicate Python or dependency conflict"
                ),
            },
            "env_drift": {
                "title": "Rollback: .env Drift Between /root and /opt Paths",
                "severity": "MEDIUM",
                "steps": [
                    "1. Compare: diff /root/loki-agents/.env /opt/loki-agents/.env",
                    "2. Source of truth is ALWAYS /root/loki-agents/.env",
                    "3. Restore: cp /root/loki-agents/.env /opt/loki-agents/.env",
                    "4. Verify: DATABASE_URL, RESEND_API_KEY, CLAUDE_API_KEY, APP_SECRET_KEY",
                    "5. Restart: docker compose down && docker compose up -d",
                    "6. Verify with a real DB-touching endpoint",
                ],
                "critical_note": (
                    "Source of truth: /root/loki-agents/.env. "
                    "Never trust /opt/.env after force-recreate."
                ),
                "escalate_if": (
                    "Critical secrets missing from BOTH files — escalate to Anthony immediately"
                ),
            },
            "general": {
                "title": "Incident Response: General Klara AI Recovery",
                "severity": "UNKNOWN",
                "steps": [
                    "1. Define scope: what is broken? API / Worker / Beat / DB / agent?",
                    "2. Run rollback_recovery snapshot to capture current state",
                    "3. Check containers: docker compose ps",
                    "4. Check recent logs: docker compose logs --tail 100 --since 30m",
                    "5. Identify last change: git log --oneline -10 or check deploy timestamp",
                    "6. Select specific playbook from supported_incidents list",
                    "7. Do NOT rollback blindly — confirm scope with Anthony first",
                ],
                "critical_note": (
                    "Always snapshot state before AND after any recovery action"
                ),
                "escalate_if": (
                    "Incident affects live lead intake or email delivery — escalate immediately"
                ),
            },
        }

        playbook = playbooks.get(incident_type, playbooks["general"])
        log.info(
            "rollback_recovery.playbook_generated",
            incident_type=incident_type,
            severity=playbook.get("severity"),
        )

        return AgentResult.ok(
            output={
                "incident_type": incident_type,
                "playbook": playbook,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "supported_incidents": _INCIDENT_TYPES,
            }
        )

    # ── Verify ────────────────────────────────────────────────────────────────

    async def _verify(self, context: AgentContext, log) -> AgentResult:
        """Post-recovery health verification."""
        checks: dict[str, str] = {}
        overall_ok = True

        # DB connectivity
        try:
            await context.db.execute(text("SELECT 1"))
            checks["db"] = "ok"
        except Exception as exc:
            checks["db"] = f"FAIL: {exc}"
            overall_ok = False

        # Alembic head
        try:
            head_q = await context.db.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            )
            row = head_q.fetchone()
            checks["alembic"] = f"ok (head: {row[0] if row else 'unknown'})"
        except Exception as exc:
            checks["alembic"] = f"FAIL: {exc}"
            overall_ok = False

        # Agent registry
        try:
            from app.agents.registry import registry
            count = len(registry.all())
            checks["agent_registry"] = f"ok ({count} agents)"
        except Exception as exc:
            checks["agent_registry"] = f"FAIL: {exc}"
            overall_ok = False

        log.info(
            "rollback_recovery.verify_complete",
            healthy=overall_ok,
            checks=checks,
        )

        return AgentResult.ok(
            output={
                "healthy": overall_ok,
                "checks": checks,
                "verified_at": datetime.now(timezone.utc).isoformat(),
            }
        )
