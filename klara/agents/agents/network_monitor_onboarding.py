"""
app/agents/network_monitor_onboarding.py
─────────────────────────────────────────
NetworkMonitorOnboardingAgent — P3 service-delivery agent.

Triggered after a Network Monitoring contract is signed.  Generates a
structured, personalised Domotz onboarding packet (Markdown) for the client
and queues it for Anthony's review before it is sent.

Trigger:  POST /api/v1/admin/deals/{lead_id}/network-monitor-onboard

Input data:
  client_name           (str)  — company / client name
  site_count            (int)  — number of physical / logical sites
  device_estimate       (int)  — estimated managed device count
  primary_contact_email (str)  — destination for the onboarding packet

Flow:
  1. Validate input.
  2. Generate personalised Markdown onboarding checklist via Claude.
  3. Create ApprovalRequest (P3) via approval_manager.
  4. Write AuditLog entry.
  5. Return AgentResult.needs_approval() with packet stored in approval payload.

Permission: P3 — client-facing document; requires Anthony's approval before send.
"""
from __future__ import annotations

import structlog
from anthropic import AsyncAnthropic

from klara.rarv.runtime import AgentContext, AgentResult, BaseAgent
from klara.rarv.runtime import PermissionLevel

logger = structlog.get_logger(__name__)

# ── Prompt ────────────────────────────────────────────────────────────────────

_ONBOARDING_PROMPT = """\
You are a senior network monitoring consultant at Klaravex.
Produce a professional Domotz onboarding checklist for a new client.

Client context:
  Company name:      {client_name}
  Number of sites:   {site_count}
  Estimated devices: {device_estimate}

Output a single Markdown document using ## for section headings.
Include exactly these sections in order:

## 1. Overview
One short paragraph describing the engagement scope and the monitoring value
for this client. Reference site_count and device_estimate specifically.

## 2. Pre-Deployment Requirements
Bullet list:
- Hardware or virtual probe per site (one probe per site is mandatory).
  Domotz hardware probe or virtual probe on ESXi / Hyper-V / KVM / Proxmox.
- Minimum spec for virtual probe host: 2 vCPU, 2 GB RAM, 8 GB disk.
- Probe must reside on the management VLAN with L2 adjacency to managed devices.
- Minimum 1 Mbps symmetric management-path bandwidth per site.
- Static IP or DHCP reservation for each probe.

## 3. SNMP Configuration Requirements
- Dedicated read-only SNMPv2c community string per site (do NOT suggest a
  specific string — the client creates one and shares it securely).
- Enable SNMP on: routers, managed switches, UPS, NAS, printers, servers
  (where applicable per site).
- UDP port 161 must be reachable from the probe IP on the management VLAN.
- For devices supporting SNMPv3: use authPriv mode, SHA-256 auth, AES-256 priv.

## 4. Network Access Requirements
Table with columns: Protocol | Port | Direction | Purpose.
Must include at minimum:
  ICMP  | —    | probe → device     | Latency monitoring / availability ping
  UDP   | 161  | probe → device     | SNMP polling
  TCP   | 22   | probe → device     | SSH (optional, for deeper diagnostics)
  TCP   | 443  | probe → internet   | Domotz cloud (api.domotz.com)
  TCP/UDP | 3351 | probe → internet | Domotz remote access tunnel

## 5. Initial Alerting Thresholds
Markdown table with columns: Alert Type | Threshold | Recommended Action.
Include: Device Offline, High Latency (>50 ms sustained), Packet Loss (>5%),
SNMP Community Unreachable, Probe Offline, Bandwidth Saturation (>80% for
15 min, where supported by device type).

## 6. Deployment Timeline
Numbered list:
  1. Probe procurement / shipping or VM provisioning — Day 0–2
  2. Probe installation and initial cloud pairing — Day 2–3
  3. Automated device discovery and topology map generation — Day 3–5
  4. SNMP community configuration and polling validation — Day 5–7
  5. Alert threshold tuning review call with client — Day 7
  6. Handover meeting and first topology map walkthrough — Day 10–14

## 7. Client Pre-Work Checklist
Bullet list of actions the client must complete before the Klaravex
engineer arrives on site or connects remotely.

Tone: professional, direct, technically precise. No marketing language.
Output ONLY the Markdown document — no preamble, no trailing explanation.
"""


class NetworkMonitorOnboardingAgent(BaseAgent):
    name = "network_monitor_onboarding"
    description = (
        "Generates a personalised Domotz onboarding packet (Markdown) after a "
        "Network Monitoring contract is signed. Creates P3 ApprovalRequest for "
        "Anthony to review before the packet is sent to the client. "
        "Trigger: POST /api/v1/admin/deals/{lead_id}/network-monitor-onboard."
    )
    permission_level = PermissionLevel.P3

    async def run(self, context: AgentContext, input_data: dict) -> AgentResult:
        db = context.db
        log = logger.bind(
            agent=self.name,
            conversation_id=str(context.conversation_id),
            request_id=str(context.request_id),
        )

        # ── Validate input ────────────────────────────────────────────────────
        client_name: str = (input_data.get("client_name") or "").strip()
        site_count_raw = input_data.get("site_count")
        device_estimate_raw = input_data.get("device_estimate")
        primary_contact_email: str = (input_data.get("primary_contact_email") or "").strip()

        missing = [
            field for field, val in [
                ("client_name", client_name),
                ("site_count", site_count_raw),
                ("device_estimate", device_estimate_raw),
                ("primary_contact_email", primary_contact_email),
            ]
            if not val and val != 0
        ]
        if missing:
            return AgentResult.fail(
                f"network_monitor_onboarding: missing required fields: {', '.join(missing)}",
                agent=self.name,
            )

        try:
            site_count = int(site_count_raw)
            device_estimate = int(device_estimate_raw)
        except (TypeError, ValueError) as exc:
            return AgentResult.fail(
                f"network_monitor_onboarding: site_count and device_estimate must be "
                f"integers — {exc}",
                agent=self.name,
            )

        if site_count < 1 or device_estimate < 1:
            return AgentResult.fail(
                "network_monitor_onboarding: site_count and device_estimate must be >= 1.",
                agent=self.name,
            )

        log.info(
            "network_monitor_onboarding.generating",
            client_name=client_name,
            site_count=site_count,
            device_estimate=device_estimate,
        )

        # ── Generate onboarding packet via Claude ─────────────────────────────
        anthropic_client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        try:
            response = await anthropic_client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=context.settings.anthropic_max_tokens,
                messages=[
                    {
                        "role": "user",
                        "content": _ONBOARDING_PROMPT.format(
                            client_name=client_name,
                            site_count=site_count,
                            device_estimate=device_estimate,
                        ),
                    }
                ],
            )
            try:
                from klara.rarv.runtime.llm_cost import track_response
                await track_response(
                    context.db, agent_name=self.name,
                    model=context.settings.anthropic_model,
                    response=response, lead_id=getattr(context, 'lead_id', None),
                )
            except Exception:
                pass
            onboarding_markdown: str = response.content[0].text.strip()
            tokens_used: int = response.usage.output_tokens
        except Exception as exc:
            log.error(
                "network_monitor_onboarding.claude_error",
                error=str(exc),
                exc_info=True,
            )
            try:
                await db.rollback()
            except Exception:
                pass
            return AgentResult.fail(
                f"network_monitor_onboarding: LLM error — {exc}",
                agent=self.name,
            )

        log.info(
            "network_monitor_onboarding.packet_generated",
            client_name=client_name,
            tokens_used=tokens_used,
            doc_length=len(onboarding_markdown),
        )

        # ── Create P3 ApprovalRequest ─────────────────────────────────────────
        approval_payload = {
            "client_name": client_name,
            "site_count": site_count,
            "device_estimate": device_estimate,
            "primary_contact_email": primary_contact_email,
            "onboarding_markdown": onboarding_markdown,
            "lead_id": context.lead_id,
        }

        try:
            from app.agents.registry import registry
            approval_mgr = registry.get("approval_manager")
            approval_result = await approval_mgr(
                context,
                {
                    "action": "create",
                    "action_name": "network_monitor_onboarding.deliver",
                    "risk_level": "P3",
                    "payload": approval_payload,
                    "justification": (
                        f"Domotz onboarding packet generated for {client_name} "
                        f"({site_count} site(s), ~{device_estimate} devices). "
                        f"Ready for review and delivery to {primary_contact_email}."
                    ),
                    "requested_by": self.name,
                },
            )
        except Exception as exc:
            log.error(
                "network_monitor_onboarding.approval_queue_error",
                error=str(exc),
                exc_info=True,
            )
            try:
                await db.rollback()
            except Exception:
                pass
            return AgentResult.fail(
                f"network_monitor_onboarding: approval queue error — {exc}",
                agent=self.name,
            )

        if not approval_result.success:
            return AgentResult.fail(
                f"network_monitor_onboarding: could not create approval request — "
                f"{approval_result.error}",
                agent=self.name,
            )

        approval_id: str = approval_result.output["approval_id"]

        # ── Write AuditLog entry ──────────────────────────────────────────────
        try:
            audit_agent = registry.get("audit_logger")
            await audit_agent(
                context,
                {
                    "event_type": "agent.action",
                    "agent_name": self.name,
                    "action_name": "network_monitor_onboarding.deliver",
                    "lead_id": context.lead_id,
                    "approval_id": approval_id,
                    "details": {
                        "client_name": client_name,
                        "site_count": site_count,
                        "device_estimate": device_estimate,
                        "tokens_used": tokens_used,
                        "status": "pending_approval",
                    },
                    "success": True,
                },
            )
        except Exception as exc:
            # Audit failure must not block the main response path.
            log.warning(
                "network_monitor_onboarding.audit_warning",
                error=str(exc),
            )

        log.info(
            "network_monitor_onboarding.queued_for_approval",
            approval_id=approval_id,
            client_name=client_name,
            lead_id=context.lead_id,
        )

        return AgentResult.needs_approval(
            approval_id=approval_id,
            action="network_monitor_onboarding.deliver",
        )
