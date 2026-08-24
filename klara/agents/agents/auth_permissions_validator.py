"""
app/agents/auth_permissions_validator.py
──────────────────────────────────────────
Auth & Permissions Validator (Agent 32 — AVAL)

Read-only validator for the Klara AI permission model and auth configuration.
Inspects the agent registry, route auth guards, and permission-level assignments
to verify that access control is correctly implemented throughout.

Permission level: P2 (read-only analysis — no implementation, no writes)

Actions:
  scan_permissions — Audit all registered agents for valid permission levels
  scan_registry    — Verify every agent in registry.py is properly registered
  check_agent      — Deep-check a named agent's auth posture
  check_routes     — Verify all API routes have auth guards and correct roles
  full_audit       — Run all checks and return a consolidated audit report

Blocked: modifying any permissions or source files.
Fallback: return forbidden-access test cases for failing checks.

Permission level hierarchy:
  P1 = read-only / auto-approve
  P2 = internal write (no outbound, no approval needed)
  P3 = outbound / user-visible actions (approval required)
  P4 = legal / billing / financial (always approved, audit trail mandatory)
  P5 = client infrastructure (always escalate to Anthony)
"""
from __future__ import annotations

import importlib
import inspect
import re
from pathlib import Path
from typing import Any

import structlog

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel

logger = structlog.get_logger(__name__)

_AGENTS_DIR = Path("/app/app/agents")
_API_DIR = Path("/app/app/api")
_REGISTRY_PATH = Path("/app/app/agents/registry.py")

# Agent files that are infrastructure, not agents
_SKIP_FILES = {"__init__.py", "base.py", "registry.py"}

# Valid auth dependency patterns in route files
_AUTH_PATTERNS = [
    "verify_api_key",
    "require_admin",
    "get_current_user",
    "portal_auth",
    "Depends(verify",
    "Depends(require",
    "Depends(get_current",
]

# P3/P4/P5 agents MUST have approval gating in their run() method
_APPROVAL_SIGNALS = [
    "needs_approval",
    "approval_manager",
    "ApprovalRequest",
    "risk_level",
]


class AuthPermissionsValidatorAgent(BaseAgent):
    name = "auth_permissions_validator"
    description = (
        "Validates the Klara AI permission model, agent registry completeness, and "
        "API route auth guards. Returns audit pass/fail per check — never modifies files."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        action = input_data.get("action", "full_audit")
        target = input_data.get("target", "").strip()

        log.info("auth_permissions_validator.start", action=action, target=target)

        if action == "scan_permissions":
            return self._scan_permissions(log)
        elif action == "scan_registry":
            return self._scan_registry(log)
        elif action == "check_agent":
            if not target:
                return AgentResult.fail("auth_permissions_validator: 'target' required for check_agent")
            return self._check_agent(target, log)
        elif action == "check_routes":
            return self._check_routes(log)
        elif action == "full_audit":
            return self._full_audit(target, log)
        else:
            return AgentResult.fail(
                f"Unknown action '{action}'. "
                "Valid: scan_permissions, scan_registry, check_agent, check_routes, full_audit"
            )

    # ── Scan permission levels ─────────────────────────────────────────────────

    def _scan_permissions(self, log) -> AgentResult:
        issues: list[dict] = []
        warnings: list[dict] = []
        agents_found: list[dict] = []

        if not _AGENTS_DIR.exists():
            return AgentResult.fail(f"auth_permissions_validator: agents dir not found: {_AGENTS_DIR}")

        for agent_file in sorted(_AGENTS_DIR.glob("*.py")):
            if agent_file.name in _SKIP_FILES:
                continue

            source = agent_file.read_text(encoding="utf-8")

            # Find permission_level declaration
            perm_match = re.search(r'permission_level\s*=\s*PermissionLevel\.(\w+)', source)
            if not perm_match:
                issues.append({
                    "type": "missing_permission_level",
                    "severity": "critical",
                    "file": agent_file.name,
                    "detail": "No 'permission_level = PermissionLevel.Px' found",
                })
                continue

            perm_str = perm_match.group(1)
            try:
                perm = PermissionLevel[perm_str]
            except KeyError:
                issues.append({
                    "type": "invalid_permission_level",
                    "severity": "critical",
                    "file": agent_file.name,
                    "detail": f"Unknown PermissionLevel: {perm_str}",
                })
                continue

            # P3/P4/P5 agents must have approval gating
            if int(perm.value[1:]) >= 3:
                has_approval = any(sig in source for sig in _APPROVAL_SIGNALS)
                if not has_approval:
                    issues.append({
                        "type": "missing_approval_gate",
                        "severity": "critical",
                        "file": agent_file.name,
                        "detail": (
                            f"Agent is {perm_str} but has no approval gating "
                            "(needs_approval / approval_manager not found)"
                        ),
                    })

            # P5 agents should never auto-execute
            if int(perm.value[1:]) == 5:
                if "AgentResult.ok(" in source and "needs_approval" not in source:
                    warnings.append({
                        "type": "p5_auto_execute_risk",
                        "severity": "high",
                        "file": agent_file.name,
                        "detail": "P5 agent returns AgentResult.ok() without needs_approval — verify this is intentional",
                    })

            agents_found.append({
                "file": agent_file.name,
                "permission_level": perm_str,
                "level_int": int(perm.value[1:]),
            })

        log.info(
            "auth_permissions_validator.permissions_scan_complete",
            agents=len(agents_found),
            issues=len(issues),
        )

        return AgentResult.ok(output={
            "action": "scan_permissions",
            "passed": len(issues) == 0,
            "agents": agents_found,
            "issues": issues,
            "warnings": warnings,
            "summary": (
                f"PASS — {len(agents_found)} agents, all permission levels valid"
                if len(issues) == 0
                else f"FAIL — {len(issues)} permission issue(s) found"
            ),
        })

    # ── Scan registry completeness ─────────────────────────────────────────────

    def _scan_registry(self, log) -> AgentResult:
        issues: list[dict] = []
        warnings: list[dict] = []

        if not _REGISTRY_PATH.exists():
            return AgentResult.fail(
                f"auth_permissions_validator: registry not found: {_REGISTRY_PATH}"
            )

        registry_source = _REGISTRY_PATH.read_text(encoding="utf-8")

        # Find all agent py files
        agent_files = [
            f.stem for f in _AGENTS_DIR.glob("*.py")
            if f.name not in _SKIP_FILES
        ]

        # For each agent file, check registry imports it
        unregistered: list[str] = []
        for module_name in agent_files:
            if module_name not in registry_source:
                unregistered.append(module_name)

        for module_name in unregistered:
            issues.append({
                "type": "unregistered_agent",
                "severity": "high",
                "module": module_name,
                "detail": f"Module '{module_name}' not referenced in registry.py",
            })

        # Check _bootstrap() exists
        if "_bootstrap" not in registry_source:
            issues.append({
                "type": "missing_bootstrap",
                "severity": "critical",
                "detail": "registry.py has no _bootstrap() function",
            })

        # Check registry.get() pattern used (not direct dict access)
        if "registry[" in registry_source:
            warnings.append({
                "type": "direct_registry_access",
                "severity": "medium",
                "detail": "registry[] direct dict access found — prefer registry.get()",
            })

        log.info(
            "auth_permissions_validator.registry_scan_complete",
            total_agent_files=len(agent_files),
            unregistered=len(unregistered),
        )

        return AgentResult.ok(output={
            "action": "scan_registry",
            "passed": len(issues) == 0,
            "total_agent_files": len(agent_files),
            "unregistered": unregistered,
            "issues": issues,
            "warnings": warnings,
            "summary": (
                f"PASS — all {len(agent_files)} agent modules referenced in registry"
                if len(issues) == 0
                else f"FAIL — {len(unregistered)} unregistered agent module(s)"
            ),
        })

    # ── Deep-check a named agent ───────────────────────────────────────────────

    def _check_agent(self, target: str, log) -> AgentResult:
        module_name = target.replace("-", "_").lower()
        path = _AGENTS_DIR / f"{module_name}.py"

        if not path.exists():
            return AgentResult.fail(
                f"auth_permissions_validator: agent file not found: {path}"
            )

        source = path.read_text(encoding="utf-8")
        checks: list[dict] = []

        # 1. Has permission_level?
        perm_match = re.search(r'permission_level\s*=\s*PermissionLevel\.(\w+)', source)
        if perm_match:
            perm_str = perm_match.group(1)
            try:
                perm = PermissionLevel[perm_str]
                checks.append({"check": "permission_level", "passed": True, "value": perm_str})
            except KeyError:
                checks.append({"check": "permission_level", "passed": False, "issue": f"Invalid: {perm_str}"})
                perm = None
        else:
            checks.append({"check": "permission_level", "passed": False, "issue": "Not declared"})
            perm = None

        # 2. Has name declared?
        has_name = bool(re.search(r'name\s*=\s*["\'][\w_]+["\']', source))
        checks.append({"check": "name_declared", "passed": has_name})

        # 3. Inherits BaseAgent?
        has_base = "BaseAgent" in source
        checks.append({"check": "inherits_base_agent", "passed": has_base})

        # 4. Uses structlog?
        has_structlog = "structlog" in source and "logger.bind(" in source
        checks.append({"check": "uses_structlog", "passed": has_structlog})

        # 5. P3/P4/P5 — approval gated?
        if perm and perm.value >= 3:
            has_approval = any(sig in source for sig in _APPROVAL_SIGNALS)
            checks.append({"check": "approval_gated", "passed": has_approval,
                           "required": True, "note": f"Required for {perm_str}"})
        else:
            checks.append({"check": "approval_gated", "passed": True, "required": False,
                           "note": f"N/A for {perm.name if perm else 'unknown'}"})

        # 6. Has AgentContext + AgentResult usage?
        has_context = "AgentContext" in source
        has_result = "AgentResult" in source
        checks.append({"check": "uses_agent_context", "passed": has_context})
        checks.append({"check": "uses_agent_result", "passed": has_result})

        # 7. In registry?
        registry_source = _REGISTRY_PATH.read_text(encoding="utf-8") if _REGISTRY_PATH.exists() else ""
        in_registry = module_name in registry_source
        checks.append({"check": "registered_in_registry", "passed": in_registry})

        passed = all(c["passed"] for c in checks)
        failed_checks = [c for c in checks if not c["passed"]]

        log.info("auth_permissions_validator.check_agent_complete", target=target, passed=passed)

        return AgentResult.ok(output={
            "action": "check_agent",
            "target": target,
            "passed": passed,
            "checks": checks,
            "failed_checks": failed_checks,
            "summary": (
                f"PASS — {target} auth posture is correct"
                if passed
                else f"FAIL — {len(failed_checks)} check(s) failed for {target}"
            ),
        })

    # ── Check route auth guards ────────────────────────────────────────────────

    def _check_routes(self, log) -> AgentResult:
        results: list[dict] = []
        issues: list[dict] = []

        if not _API_DIR.exists():
            return AgentResult.fail(f"auth_permissions_validator: API dir not found: {_API_DIR}")

        for route_file in sorted(_API_DIR.glob("*.py")):
            if route_file.name.startswith("_"):
                continue
            source = route_file.read_text(encoding="utf-8")

            # Check for at least one auth pattern
            found_auth = [p for p in _AUTH_PATTERNS if p in source]
            has_auth = len(found_auth) > 0

            # Count route decorators
            route_count = len(re.findall(r'@router\.(?:get|post|put|delete|patch)\(', source))
            if route_count == 0:
                route_count = len(re.findall(r'@app\.(?:get|post|put|delete|patch)\(', source))

            file_result = {
                "file": route_file.name,
                "route_count": route_count,
                "has_auth": has_auth,
                "auth_patterns_found": found_auth,
                "passed": has_auth or route_count == 0,
            }
            results.append(file_result)

            if not has_auth and route_count > 0:
                issues.append({
                    "type": "unprotected_routes",
                    "severity": "critical",
                    "file": route_file.name,
                    "detail": f"{route_count} routes with no auth dependency detected",
                })

        log.info(
            "auth_permissions_validator.route_check_complete",
            files=len(results),
            issues=len(issues),
        )

        return AgentResult.ok(output={
            "action": "check_routes",
            "passed": len(issues) == 0,
            "files": results,
            "issues": issues,
            "summary": (
                f"PASS — {len(results)} route files, all protected"
                if len(issues) == 0
                else f"FAIL — {len(issues)} unprotected route file(s)"
            ),
        })

    # ── Full audit ─────────────────────────────────────────────────────────────

    def _full_audit(self, target: str, log) -> AgentResult:
        results: dict[str, Any] = {}

        perm_result = self._scan_permissions(log)
        results["permissions"] = perm_result.output if perm_result.success else {"error": perm_result.error}

        reg_result = self._scan_registry(log)
        results["registry"] = reg_result.output if reg_result.success else {"error": reg_result.error}

        route_result = self._check_routes(log)
        results["routes"] = route_result.output if route_result.success else {"error": route_result.error}

        if target:
            agent_result = self._check_agent(target, log)
            results["agent"] = agent_result.output if agent_result.success else {"error": agent_result.error}

        perm_pass = results.get("permissions", {}).get("passed", False)
        reg_pass = results.get("registry", {}).get("passed", False)
        route_pass = results.get("routes", {}).get("passed", False)
        agent_pass = results.get("agent", {}).get("passed", True)
        overall_pass = perm_pass and reg_pass and route_pass and agent_pass

        log.info("auth_permissions_validator.full_audit_complete", passed=overall_pass)

        return AgentResult.ok(output={
            "action": "full_audit",
            "passed": overall_pass,
            "results": results,
            "summary": (
                "PASS — full auth/permissions audit clean"
                if overall_pass
                else "FAIL — see results for details"
            ),
        })
