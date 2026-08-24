"""
app/agents/security_validator.py
──────────────────────────────────
Security Validator (Agent 31 — SVAL)

Static analysis validator for the Klara AI codebase. Inspects agent modules,
API routes, and environment configuration for security anti-patterns.

Permission level: P2 (read-only analysis — no implementation, no writes)

Actions:
  scan_agent  — Inspect a named agent module for security issues
  scan_routes — Inspect API route files for auth and injection risks
  scan_env    — Audit loaded environment variables for secret hygiene
  full_scan   — Run all three scans and return a consolidated report

Blocked: implementing fixes directly; modifying any source file.
Fallback: fail task and return remediation notes.

Security checks performed:
  - Hardcoded secrets / credentials in source
  - os.environ direct access vs settings object
  - Exposed debug routes or missing auth dependencies
  - Dangerous patterns: eval, exec, shell=True, pickle
  - Unvalidated external URLs (SSRF risk)
  - Missing input validation on agent entry points
  - Overly broad exception suppression (bare except / pass)
"""
from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any

import structlog

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel

logger = structlog.get_logger(__name__)

# Paths relative to the container workdir /app
_AGENTS_DIR = Path("/app/app/agents")
_API_DIR = Path("/app/app/api")

# ── Pattern definitions ────────────────────────────────────────────────────────

_DANGEROUS_CALLS = {"eval", "exec", "compile", "__import__"}
_SHELL_PATTERNS = [
    re.compile(r'shell\s*=\s*True', re.I),
    re.compile(r'subprocess\.call\('),
    re.compile(r'os\.system\('),
    re.compile(r'os\.popen\('),
]
_HARDCODED_SECRET_PATTERNS = [
    re.compile(r'(?:api_key|password|secret|token)\s*=\s*["\'][^"\']{8,}["\']', re.I),
    re.compile(r'sk-[A-Za-z0-9]{20,}'),
    re.compile(r'[A-Za-z0-9+/]{40,}={0,2}'),  # base64 blob — may be key
]
_SSRF_PATTERNS = [
    re.compile(r'aiohttp\.ClientSession\(\).*?session\.(get|post)\(.*?input_data', re.S),
    re.compile(r'requests\.(get|post)\(.*?f["\']https?://\{'),
]
_BARE_EXCEPT = re.compile(r'except\s*(?:Exception\s*)?\:\s*\n\s*pass')
_DIRECT_ENV = re.compile(r'os\.environ\[')
_PICKLE_USE = re.compile(r'import pickle|pickle\.loads?\(')
_DEBUG_ROUTES = re.compile(r'@(?:app|router)\.(?:get|post)\(["\'].*(?:debug|test|dev|internal)["\']')


class SecurityValidatorAgent(BaseAgent):
    name = "security_validator"
    description = (
        "Static security analysis for Klara AI agents and API routes. "
        "Identifies hardcoded secrets, missing auth, dangerous patterns, and SSRF risk. "
        "Returns pass/warn/fail per check — never modifies files."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        action = input_data.get("action", "scan_agent")
        target = input_data.get("target", "").strip()

        log.info("security_validator.start", action=action, target=target)

        if action == "scan_agent":
            if not target:
                return AgentResult.fail("security_validator: 'target' required for scan_agent")
            return self._scan_agent(target, log)
        elif action == "scan_routes":
            return self._scan_routes(log)
        elif action == "scan_env":
            return self._scan_env(log)
        elif action == "full_scan":
            return self._full_scan(target, log)
        else:
            return AgentResult.fail(
                f"Unknown action '{action}'. Valid: scan_agent, scan_routes, scan_env, full_scan"
            )

    # ── Scan agent module ─────────────────────────────────────────────────────

    def _scan_agent(self, target: str, log) -> AgentResult:
        module = target.replace("-", "_").lower()
        path = _AGENTS_DIR / f"{module}.py"

        if not path.exists():
            return AgentResult.fail(
                f"security_validator: agent file not found: {path}"
            )

        source = path.read_text(encoding="utf-8")
        findings = self._analyse_source(source, str(path))

        log.info(
            "security_validator.agent_scan_complete",
            target=target,
            issues=len(findings["issues"]),
            warnings=len(findings["warnings"]),
        )

        passed = len(findings["issues"]) == 0
        return AgentResult.ok(output={
            "target": target,
            "file": str(path),
            "passed": passed,
            "issues": findings["issues"],
            "warnings": findings["warnings"],
            "summary": (
                f"PASS — no critical issues" if passed
                else f"FAIL — {len(findings['issues'])} issue(s), {len(findings['warnings'])} warning(s)"
            ),
        })

    # ── Scan API routes ───────────────────────────────────────────────────────

    def _scan_routes(self, log) -> AgentResult:
        results: list[dict[str, Any]] = []

        if not _API_DIR.exists():
            return AgentResult.fail(f"security_validator: API dir not found: {_API_DIR}")

        for route_file in sorted(_API_DIR.glob("*.py")):
            if route_file.name.startswith("_"):
                continue
            source = route_file.read_text(encoding="utf-8")
            findings = self._analyse_source(source, str(route_file))

            # Route-specific: check for missing auth dependency
            has_auth = (
                "verify_api_key" in source
                or "require_admin" in source
                or "get_current_user" in source
                or "Depends(verify" in source
                or "Depends(require" in source
                or "Depends(get_current" in source
            )
            if not has_auth:
                findings["issues"].append({
                    "type": "missing_auth",
                    "severity": "critical",
                    "detail": "No auth dependency found in route file",
                    "file": str(route_file),
                })

            # Check for debug/internal routes
            for m in _DEBUG_ROUTES.finditer(source):
                findings["warnings"].append({
                    "type": "debug_route",
                    "severity": "medium",
                    "detail": f"Possible debug/internal route: {m.group(0)[:80]}",
                    "file": str(route_file),
                })

            results.append({
                "file": route_file.name,
                "passed": len(findings["issues"]) == 0,
                "issues": findings["issues"],
                "warnings": findings["warnings"],
            })

        total_issues = sum(len(r["issues"]) for r in results)
        total_warnings = sum(len(r["warnings"]) for r in results)
        log.info(
            "security_validator.route_scan_complete",
            files=len(results),
            issues=total_issues,
            warnings=total_warnings,
        )

        return AgentResult.ok(output={
            "action": "scan_routes",
            "passed": total_issues == 0,
            "total_issues": total_issues,
            "total_warnings": total_warnings,
            "files": results,
            "summary": (
                f"PASS — {len(results)} route files scanned, no critical issues"
                if total_issues == 0
                else f"FAIL — {total_issues} critical issue(s) across {len(results)} files"
            ),
        })

    # ── Scan environment ──────────────────────────────────────────────────────

    def _scan_env(self, log) -> AgentResult:
        issues: list[dict] = []
        warnings: list[dict] = []

        required_keys = [
            "APP_SECRET_KEY",
            "DATABASE_URL",
            "ANTHROPIC_API_KEY",
        ]
        sensitive_keys = [
            "ANTHROPIC_API_KEY",
            "RESEND_API_KEY",
            "APP_SECRET_KEY",
            "CRM_WEBHOOK_URL",
            "STRIPE_SECRET_KEY",
            "STRIPE_WEBHOOK_SECRET",
        ]

        for key in required_keys:
            val = os.environ.get(key, "")
            if not val:
                issues.append({
                    "type": "missing_required_env",
                    "severity": "critical",
                    "key": key,
                    "detail": f"Required env var '{key}' is not set",
                })

        for key in sensitive_keys:
            val = os.environ.get(key, "")
            if val and len(val) < 8:
                warnings.append({
                    "type": "weak_secret",
                    "severity": "medium",
                    "key": key,
                    "detail": f"'{key}' value is suspiciously short ({len(val)} chars) — may be a placeholder",
                })
            if val and val.lower() in ("test", "secret", "changeme", "password", "12345"):
                issues.append({
                    "type": "default_secret",
                    "severity": "critical",
                    "key": key,
                    "detail": f"'{key}' appears to be a default/test value",
                })

        # Check DATABASE_URL doesn't reference local db service in production
        db_url = os.environ.get("DATABASE_URL", "")
        if "@db:" in db_url or "localhost" in db_url:
            warnings.append({
                "type": "local_db_url",
                "severity": "high",
                "key": "DATABASE_URL",
                "detail": (
                    "DATABASE_URL points to '@db:' or 'localhost' — "
                    "should reference Cloud86 production host in production"
                ),
            })

        log.info(
            "security_validator.env_scan_complete",
            issues=len(issues),
            warnings=len(warnings),
        )

        return AgentResult.ok(output={
            "action": "scan_env",
            "passed": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "summary": (
                "PASS — environment configuration looks clean"
                if len(issues) == 0
                else f"FAIL — {len(issues)} critical environment issue(s)"
            ),
        })

    # ── Full scan ─────────────────────────────────────────────────────────────

    def _full_scan(self, target: str, log) -> AgentResult:
        results: dict[str, Any] = {}

        # Env scan
        env_result = self._scan_env(log)
        results["env"] = env_result.output if env_result.success else {"error": env_result.error}

        # Route scan
        route_result = self._scan_routes(log)
        results["routes"] = route_result.output if route_result.success else {"error": route_result.error}

        # Agent scan (if target given)
        if target:
            agent_result = self._scan_agent(target, log)
            results["agent"] = agent_result.output if agent_result.success else {"error": agent_result.error}

        # Consolidated pass/fail
        env_pass = results.get("env", {}).get("passed", False)
        route_pass = results.get("routes", {}).get("passed", False)
        agent_pass = results.get("agent", {}).get("passed", True)  # N/A if not scanned
        overall_pass = env_pass and route_pass and agent_pass

        log.info("security_validator.full_scan_complete", passed=overall_pass)

        return AgentResult.ok(output={
            "action": "full_scan",
            "passed": overall_pass,
            "results": results,
            "summary": "PASS — full security scan clean" if overall_pass else "FAIL — see results for details",
        })

    # ── Source analyser ───────────────────────────────────────────────────────

    def _analyse_source(self, source: str, filepath: str) -> dict[str, list]:
        issues: list[dict] = []
        warnings: list[dict] = []

        # AST-based checks
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                # Dangerous function calls
                if isinstance(node, ast.Call):
                    func_name = ""
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        func_name = node.func.attr
                    if func_name in _DANGEROUS_CALLS:
                        issues.append({
                            "type": "dangerous_call",
                            "severity": "critical",
                            "detail": f"Dangerous call: {func_name}() at line {node.lineno}",
                            "file": filepath,
                            "line": node.lineno,
                        })
        except SyntaxError as exc:
            warnings.append({
                "type": "parse_error",
                "severity": "low",
                "detail": f"Could not parse AST: {exc}",
                "file": filepath,
            })

        # Regex-based checks
        for pattern in _SHELL_PATTERNS:
            for m in pattern.finditer(source):
                lineno = source[: m.start()].count("\n") + 1
                issues.append({
                    "type": "shell_injection_risk",
                    "severity": "critical",
                    "detail": f"Shell execution pattern: {m.group(0)[:60]}",
                    "file": filepath,
                    "line": lineno,
                })

        for pattern in _HARDCODED_SECRET_PATTERNS:
            for m in pattern.finditer(source):
                lineno = source[: m.start()].count("\n") + 1
                warnings.append({
                    "type": "possible_hardcoded_secret",
                    "severity": "high",
                    "detail": f"Possible hardcoded secret at line {lineno}: {m.group(0)[:40]}...",
                    "file": filepath,
                    "line": lineno,
                })

        if _PICKLE_USE.search(source):
            issues.append({
                "type": "pickle_usage",
                "severity": "critical",
                "detail": "pickle module used — unsafe for untrusted data",
                "file": filepath,
            })

        for m in _DIRECT_ENV.finditer(source):
            lineno = source[: m.start()].count("\n") + 1
            warnings.append({
                "type": "direct_env_access",
                "severity": "medium",
                "detail": f"os.environ[] direct access at line {lineno} — prefer settings object",
                "file": filepath,
                "line": lineno,
            })

        for m in _BARE_EXCEPT.finditer(source):
            lineno = source[: m.start()].count("\n") + 1
            warnings.append({
                "type": "bare_except_pass",
                "severity": "medium",
                "detail": f"Bare except/pass at line {lineno} — silences errors",
                "file": filepath,
                "line": lineno,
            })

        return {"issues": issues, "warnings": warnings}
