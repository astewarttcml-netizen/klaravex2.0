"""
app/agents/test_harness.py
───────────────────────────
Test Harness Builder (Agent 26 — TEST)

Generates unit, integration, and regression test scaffolding for Klara AI agents
and API routes. Uses Claude to produce pytest-asyncio-compatible test stubs.

Permission level: P2 (read + internal write — returns test file content only)

Actions:
  generate  — Generate a pytest test file for a named agent or module
  fixtures  — Generate pytest fixtures for a named agent
  analyze   — Identify untested agents by scanning agents/ vs tests/ directories

Blocked: mutating production data. No DB writes.
Fallback: mark coverage gap and return empty stub with TODO markers.
"""
from __future__ import annotations

import os
import re

import structlog
from anthropic import AsyncAnthropic

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel

logger = structlog.get_logger(__name__)


class TestHarnessAgent(BaseAgent):
    name = "test_harness"
    description = (
        "Generates pytest test stubs, fixtures, and coverage analysis for "
        "Klara AI agents and API routes. Returns file content — does not write files."
    )
    permission_level = PermissionLevel.P2

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        log = logger.bind(
            agent=self.name,
            conversation=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        action = input_data.get("action", "generate")
        target = input_data.get("target", "").strip()
        test_type = input_data.get("test_type", "unit")

        log.info("test_harness.start", action=action, target=target, test_type=test_type)

        if action == "generate":
            if not target:
                return AgentResult.fail("test_harness: 'target' required for generate")
            return await self._generate(context, target, test_type, log)
        elif action == "fixtures":
            if not target:
                return AgentResult.fail("test_harness: 'target' required for fixtures")
            return await self._fixtures(context, target, log)
        elif action == "analyze":
            return self._analyze(log)
        else:
            return AgentResult.fail(
                f"Unknown action '{action}'. Valid: generate, fixtures, analyze"
            )

    # ── Generate ──────────────────────────────────────────────────────────────

    async def _generate(
        self, context: AgentContext, target: str, test_type: str, log
    ) -> AgentResult:
        module = target.replace("-", "_").lower()
        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)

        prompt = f"""Write a complete pytest-asyncio test file for the Klara AI agent: `{target}`.

Module path: `app.agents.{module}`
Test type: {test_type}

Requirements:
- `import pytest` and `pytest.mark.asyncio` on every async test
- `from unittest.mock import AsyncMock, MagicMock, patch`
- A `make_context()` fixture that returns a minimal `AgentContext`
  (db=AsyncMock(), settings=MagicMock(anthropic_api_key="sk-test", anthropic_model="claude-opus-4-5"), conversation_id=uuid4(), request_id=uuid4())
- Cover: happy path, missing required input, agent returning AgentResult.fail()
- If the agent calls Claude, patch `anthropic.AsyncAnthropic` — never call real API
- File must be runnable with `pytest tests/test_{module}.py` out of the box

Return only the Python code, no markdown fences or explanation."""

        try:
            msg = await client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=1800,
                system=(
                    "You are a senior Python engineer writing production-quality pytest tests "
                    "for a FastAPI + SQLAlchemy async backend. Be concise, correct, and runnable."
                ),
                messages=[{"role": "user", "content": prompt}],
            )
            from app.services.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model=context.settings.anthropic_model,
                response=msg,
            )
            code = msg.content[0].text.strip()
        except Exception as exc:
            log.error("test_harness.claude_error", error=str(exc))
            code = (
                f"# TODO: Claude generation failed — {exc}\n"
                f"# Stub for app.agents.{module}\n"
                f"import pytest\nfrom unittest.mock import AsyncMock, MagicMock\n"
                f"from uuid import uuid4\n\n"
                f"# Add tests for {target} here\n"
            )

        log.info("test_harness.generate_complete", target=target, chars=len(code))
        return AgentResult.ok(
            output={
                "target": target,
                "test_type": test_type,
                "filename": f"tests/test_{module}.py",
                "content": code,
                "char_count": len(code),
            }
        )

    # ── Fixtures ──────────────────────────────────────────────────────────────

    async def _fixtures(self, context: AgentContext, target: str, log) -> AgentResult:
        module = target.replace("-", "_").lower()
        client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)

        try:
            msg = await client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=700,
                messages=[{"role": "user", "content": (
                    f"Write 3–5 pytest fixtures for testing the Klara AI agent `{target}` "
                    f"(module: app.agents.{module}). "
                    "Include: make_context(), mock_db(), mock_settings(), and any "
                    "agent-specific fixtures. Use @pytest.fixture and AsyncMock. "
                    "Return Python code only, no explanation."
                )}],
            )
            from app.services.llm_cost import track_response
            await track_response(
                context.db, agent_name=self.name,
                model=context.settings.anthropic_model,
                response=msg,
            )
            code = msg.content[0].text.strip()
        except Exception as exc:
            return AgentResult.fail(f"test_harness.fixtures: Claude error — {exc}")

        return AgentResult.ok(output={"target": target, "fixtures": code})

    # ── Analyze ───────────────────────────────────────────────────────────────

    def _analyze(self, log) -> AgentResult:
        """Scan agents/ and tests/ to surface untested agents."""
        agents_dir = "/app/app/agents"
        tests_dir = "/app/tests"

        agent_modules: list[str] = []
        try:
            agent_modules = [
                f[:-3]
                for f in os.listdir(agents_dir)
                if f.endswith(".py") and not f.startswith("_") and f != "base.py"
            ]
        except OSError:
            pass

        tested: set[str] = set()
        try:
            if os.path.isdir(tests_dir):
                for tf in os.listdir(tests_dir):
                    m = re.match(r"test_(.+)\.py", tf)
                    if m:
                        tested.add(m.group(1))
        except OSError:
            pass

        agent_set = set(agent_modules)
        covered = sorted(tested & agent_set)
        untested = sorted(agent_set - tested)
        pct = round(len(covered) / max(len(agent_modules), 1) * 100, 1)

        log.info(
            "test_harness.analyze_complete",
            total=len(agent_modules),
            covered=len(covered),
            untested=len(untested),
            coverage_pct=pct,
        )

        return AgentResult.ok(
            output={
                "total_agents": len(agent_modules),
                "covered": covered,
                "untested": untested,
                "coverage_pct": pct,
            }
        )
