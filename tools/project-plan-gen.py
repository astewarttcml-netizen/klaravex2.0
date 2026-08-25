#!/usr/bin/env python3
"""
project-plan-gen.py — Klaravex B2B Project Plan Generator

Usage:
    python tools/project-plan-gen.py \
        --sku m365-migration \
        --client "Acme Corp" \
        --users 25 \
        --output plans/

Generates a markdown project plan from a hardcoded SKU template and
(optionally) the corresponding A6_<sku>.yaml state machine. Also inserts
a klaravex_tickets row with type='project', status='scoped'.

Supported SKUs:
    m365-migration          Microsoft 365 migration
    azure-project           Azure architecture / migration project
    backup-dr-setup         Backup and DR setup
    intune-rollout          Intune MDM rollout
    windows-server-project  Windows Server + AD project
    powershell-project      PowerShell automation project
    firewall-deploy         Firewall / network deployment
    network-monitoring      Network monitoring setup

Environment:
    DATABASE_URL — asyncpg-compatible Postgres DSN
    (Bun auto-loads .env; for Python use a .env file or set vars manually)
"""

import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    import asyncpg
    HAS_ASYNCPG = True
except ImportError:
    HAS_ASYNCPG = False


# ---------------------------------------------------------------------------
# SKU templates
# ---------------------------------------------------------------------------

SKU_TEMPLATES: dict[str, dict] = {

    "m365-migration": {
        "name": "Microsoft 365 Migration",
        "description": (
            "Zero-downtime migration from on-premises Exchange or Google Workspace "
            "to Microsoft 365. Includes mailbox migration, DNS cutover, SharePoint/OneDrive "
            "setup, and 72-hour stabilisation monitoring."
        ),
        "timeline_weeks": 4,
        "states": ["SCOPED", "PILOT", "MIGRATION", "CUTOVER", "STABILIZATION", "CLOSED"],
        "deliverables": [
            "Scoping intake and environment inventory",
            "Project plan with milestones and cutover window",
            "Pilot migration (1–3 test mailboxes)",
            "Full mailbox migration in scheduled batches",
            "DNS cutover with rollback plan",
            "72-hour stabilisation monitoring",
            "Handoff documentation (admin guide, DNS records reference)",
            "Final walkthrough call with senior engineer",
            "30-day stability check",
        ],
        "acceptance_criteria": [
            "All mailboxes fully migrated with email delivery confirmed",
            "MX/SPF/DKIM/DMARC DNS records updated and propagated",
            "No mail loss detected during 72-hour stabilisation window",
            "All users can send and receive email from M365",
            "SharePoint/OneDrive accessible for all licensed users",
            "Handoff documentation delivered and walkthrough completed",
        ],
        "risks": [
            {
                "risk": "Large mailboxes exceed migration window",
                "likelihood": "Medium",
                "mitigation": "Pre-stage migration in off-hours batches; stagger largest mailboxes first",
            },
            {
                "risk": "DNS TTL delays extend cutover downtime",
                "likelihood": "Low",
                "mitigation": "Lower TTLs 48 hours before cutover window to 300s",
            },
            {
                "risk": "Legacy connectors/integrations break after cutover",
                "likelihood": "Medium",
                "mitigation": "Inventory all SMTP relay dependencies during scoping; update before cutover",
            },
            {
                "risk": "Client staff resistance to new interface",
                "likelihood": "Low",
                "mitigation": "Include M365 quick-start guide in handoff documentation",
            },
        ],
        "comms_plan": [
            {"trigger": "SOW signed", "action": "Kickoff email + scoping intake form sent"},
            {"trigger": "Weekly during migration", "action": "Status update email to primary contact"},
            {"trigger": "48h before cutover", "action": "Cutover schedule confirmation email"},
            {"trigger": "Cutover complete", "action": "Immediate confirmation email with next steps"},
            {"trigger": "Day 30", "action": "Stability check email"},
            {"trigger": "Day 60", "action": "Managed plan upsell email"},
        ],
    },

    "azure-project": {
        "name": "Azure Architecture / Migration Project",
        "description": (
            "Azure infrastructure deployment or migration project. Covers greenfield "
            "Azure deployments, lift-and-shift from on-premises or AWS, Azure Virtual "
            "Desktop (AVD), and Entra ID / hybrid identity configuration."
        ),
        "timeline_weeks": 6,
        "states": ["SCOPED", "DISCOVERY", "DESIGN", "PILOT", "MIGRATION", "CUTOVER", "HYPERCARE", "CLOSED"],
        "deliverables": [
            "Discovery report (workload inventory, dependency map)",
            "Architecture design document with cost estimate",
            "IaC scaffold (Bicep or Terraform)",
            "Pilot deployment in non-production environment",
            "Phased production migration with SOW-gated steps",
            "Cutover with documented rollback plan",
            "72-hour hypercare monitoring (Azure Monitor + cost alerts)",
            "Handoff documentation (architecture diagram, admin guide, runbook)",
            "Final walkthrough call with senior engineer",
            "30-day stability check",
        ],
        "acceptance_criteria": [
            "All in-scope workloads running in Azure with health checks passing",
            "Azure Monitor alerts configured for all production resources",
            "Cost baseline established and anomaly alerts active",
            "Entra ID / hybrid sync verified (if in scope)",
            "Rollback plan tested or documented with recovery steps",
            "IaC scaffold checked in to client's repository",
            "Handoff documentation delivered and walkthrough completed",
        ],
        "risks": [
            {
                "risk": "Undetected dependencies surface during migration",
                "likelihood": "Medium",
                "mitigation": "Thorough discovery phase; dependency mapping before design sign-off",
            },
            {
                "risk": "Cost overrun due to under-sized estimates",
                "likelihood": "Low",
                "mitigation": "Azure Pricing Calculator estimate in design doc; cost alerts from day 1",
            },
            {
                "risk": "Hybrid identity sync errors after cutover",
                "likelihood": "Medium",
                "mitigation": "Entra Connect staging mode validation before cutover",
            },
            {
                "risk": "Licensing gaps for required Azure services",
                "likelihood": "Low",
                "mitigation": "License inventory during discovery; flag gaps before design approval",
            },
        ],
        "comms_plan": [
            {"trigger": "SOW signed", "action": "Kickoff email + scoping intake form sent"},
            {"trigger": "Discovery complete", "action": "Discovery findings report delivered for review"},
            {"trigger": "Design approved", "action": "Design document + cost estimate delivered"},
            {"trigger": "Every 2 days during migration", "action": "Status update email to primary contact"},
            {"trigger": "Cutover complete", "action": "Confirmation email with hypercare details"},
            {"trigger": "Day 30", "action": "Stability check email"},
        ],
    },

    "backup-dr-setup": {
        "name": "Backup and Disaster Recovery Setup",
        "description": (
            "End-to-end backup and DR implementation. Covers endpoint backup, server backup, "
            "M365 backup (Exchange, SharePoint, OneDrive), cloud-to-cloud backup, and a "
            "DR runbook with a tested failover to meet defined RTO/RPO targets."
        ),
        "timeline_weeks": 3,
        "states": ["SCOPED", "INVENTORY", "DESIGN", "DEPLOY_BACKUP", "DEPLOY_DR", "TEST_FAILOVER", "DOCUMENTED", "CLOSED"],
        "deliverables": [
            "Asset inventory (servers, endpoints, M365, cloud resources)",
            "Backup and DR design document with RTO/RPO mapping",
            "Backup deployment across all in-scope systems",
            "DR target configuration (off-site replication or cloud DR vault)",
            "Completed DR runbook with step-by-step recovery procedures",
            "Tested failover with documented results vs. RTO/RPO targets",
            "Final documentation package (config, retention schedules, runbook, test results)",
            "Final walkthrough call with senior engineer",
            "30-day backup health check",
        ],
        "acceptance_criteria": [
            "All in-scope systems have backup agents/jobs running and confirmed healthy",
            "First backup of each system completed and verified restorable",
            "DR replication or vault configured and reachable",
            "Failover test completed; actual RTO/RPO within agreed targets",
            "DR runbook reviewed and signed off by client primary contact",
            "Backup monitoring alerts configured to notify on failure",
        ],
        "risks": [
            {
                "risk": "Initial backup of large data sets exceeds window",
                "likelihood": "Medium",
                "mitigation": "Seed large backups during off-hours; use differential thereafter",
            },
            {
                "risk": "RTO/RPO targets unachievable with current infrastructure",
                "likelihood": "Low",
                "mitigation": "Gap analysis during design phase; escalate infrastructure upgrade recommendation",
            },
            {
                "risk": "M365 backup licensing gap",
                "likelihood": "Low",
                "mitigation": "Verify M365 backup product licensing during inventory phase",
            },
            {
                "risk": "Failover test causes production disruption",
                "likelihood": "Low",
                "mitigation": "Schedule test in agreed maintenance window; isolate test from live traffic",
            },
        ],
        "comms_plan": [
            {"trigger": "SOW signed", "action": "Kickoff email + scoping intake sent"},
            {"trigger": "Design approved", "action": "Design document delivered for sign-off"},
            {"trigger": "Every 2 days during deployment", "action": "Status update email"},
            {"trigger": "Failover test scheduled", "action": "Advance notice email with maintenance window details"},
            {"trigger": "Project complete", "action": "Final documentation package delivered"},
            {"trigger": "Day 30", "action": "Backup health check email"},
        ],
    },

    "intune-rollout": {
        "name": "Intune MDM Rollout",
        "description": (
            "Microsoft Intune MDM rollout across all endpoint platforms. Covers tenant "
            "configuration, compliance and configuration policies, conditional access, "
            "app deployment, Windows Autopilot, and BYOD enrollment (iOS/Android)."
        ),
        "timeline_weeks": 4,
        "states": ["SCOPED", "TENANT_CONFIG", "POLICY_DESIGN", "PILOT_GROUP", "FULL_ROLLOUT", "MONITORING", "CLOSED"],
        "deliverables": [
            "Intune tenant configuration (MDM authority, enrollment restrictions, connectors)",
            "Policy design document (compliance, config profiles, conditional access, app protection)",
            "Pilot group rollout with compliance validation and user feedback",
            "Full device enrollment across all platforms",
            "App deployment assignments via Intune",
            "7-day compliance monitoring post-rollout",
            "Final documentation (policy inventory, admin guide, compliance baseline)",
            "Final walkthrough call with senior engineer",
            "30-day compliance health check",
        ],
        "acceptance_criteria": [
            "All enrolled devices show compliant status in Intune dashboard",
            "Conditional access policies blocking non-compliant devices verified",
            "Required apps deployed to all in-scope device groups",
            "BYOD enrollment working on iOS and Android (if in scope)",
            "Windows Autopilot tested end-to-end (if in scope)",
            "Zero-touch enrollment tested for at least one new device",
            "Policy inventory documentation delivered and reviewed",
        ],
        "risks": [
            {
                "risk": "Conditional access policies lock out users unexpectedly",
                "likelihood": "Medium",
                "mitigation": "Apply policies to pilot group first; test all access scenarios before full rollout",
            },
            {
                "risk": "Legacy devices cannot meet compliance baselines",
                "likelihood": "Low",
                "mitigation": "Identify legacy devices during scoping; create compliant exception policy if needed",
            },
            {
                "risk": "BYOD privacy concerns from employees",
                "likelihood": "Low",
                "mitigation": "Include BYOD privacy policy explainer in pilot communications",
            },
            {
                "risk": "GDAP access delays from Microsoft",
                "likelihood": "Low",
                "mitigation": "Initiate GDAP request immediately after SOW signing",
            },
        ],
        "comms_plan": [
            {"trigger": "SOW signed", "action": "Kickoff email + scoping intake sent"},
            {"trigger": "Policy design approved", "action": "Policy document delivered for sign-off"},
            {"trigger": "Pilot group launch", "action": "Pilot notification email to pilot users"},
            {"trigger": "Every 2 days during rollout", "action": "Enrollment progress update email"},
            {"trigger": "Rollout complete", "action": "Compliance baseline report delivered"},
            {"trigger": "Day 30", "action": "Compliance health check email"},
        ],
    },

    "windows-server-project": {
        "name": "Windows Server and Active Directory Project",
        "description": (
            "Windows Server and Active Directory infrastructure project. Covers new AD "
            "domain setups, DC promotions, server builds, server OS upgrades, file server "
            "migrations, and hybrid identity (Entra ID Connect) configurations."
        ),
        "timeline_weeks": 5,
        "states": ["SCOPED", "DESIGN", "BUILD", "MIGRATION", "TESTING", "CUTOVER", "CLOSED"],
        "deliverables": [
            "Infrastructure design document (AD structure, OU design, GPO framework, FSMO placement)",
            "New server environment build (bare metal or VM)",
            "Data and workload migration (file server, user accounts, GPOs)",
            "Acceptance test results against documented criteria",
            "Production cutover within agreed maintenance window",
            "Handoff documentation (AD diagram, GPO inventory, server inventory, admin guide)",
            "Final walkthrough call with senior engineer",
            "30-day stability check",
        ],
        "acceptance_criteria": [
            "AD replication healthy across all domain controllers",
            "All user accounts and groups migrated and verified",
            "GPOs applying correctly to all OUs and verified on sample machines",
            "DNS and DHCP services operational with no errors",
            "File share access working for all migrated shares",
            "Hybrid identity sync verified in Entra ID (if in scope)",
            "All legacy systems decommissioned or documented for decommission",
        ],
        "risks": [
            {
                "risk": "Replication failures during DC promotion",
                "likelihood": "Low",
                "mitigation": "Validate DNS health and firewall rules before DC promotion; staged rollout",
            },
            {
                "risk": "GPO migration conflicts with existing group policies",
                "likelihood": "Medium",
                "mitigation": "GPO audit and conflict analysis during design phase",
            },
            {
                "risk": "File server data volume exceeds migration window",
                "likelihood": "Medium",
                "mitigation": "Pre-stage file server data with Robocopy; final delta sync at cutover",
            },
            {
                "risk": "Application Kerberos dependencies break post-migration",
                "likelihood": "Low",
                "mitigation": "Application dependency audit during scoping; SPN review before cutover",
            },
        ],
        "comms_plan": [
            {"trigger": "SOW signed", "action": "Kickoff email + scoping intake sent"},
            {"trigger": "Design approved", "action": "Design document delivered for sign-off"},
            {"trigger": "Every 2 days during build", "action": "Status update email"},
            {"trigger": "48h before cutover", "action": "Cutover schedule confirmation with maintenance window details"},
            {"trigger": "Cutover complete", "action": "Confirmation email with post-cutover verification steps"},
            {"trigger": "Day 30", "action": "Stability check email"},
        ],
    },

    "powershell-project": {
        "name": "PowerShell Automation Project",
        "description": (
            "Custom PowerShell automation project. Covers user lifecycle automation, "
            "bulk operations against AD/M365/Azure, automated reporting, monitoring "
            "scripts, and deployment to Task Scheduler or Azure Automation."
        ),
        "timeline_weeks": 3,
        "states": ["SCOPED", "REQUIREMENTS", "SCRIPT_DEV", "TESTING", "STAGING", "PRODUCTION", "DOCUMENTATION", "CLOSED"],
        "deliverables": [
            "Requirements document (inputs, outputs, logic, acceptance criteria, security model)",
            "Script scaffold (parameter validation, error handling, logging patterns)",
            "Completed PowerShell script with full business logic",
            "Test results against documented acceptance criteria",
            "Staging run with client review and approval",
            "Production deployment (Task Scheduler / Azure Automation / RMM)",
            "Complete documentation (parameter reference, schedule, error guide, maintenance guide)",
            "Final walkthrough call with senior engineer",
            "30-day health check",
        ],
        "acceptance_criteria": [
            "Script produces expected output matching requirements spec on all test cases",
            "Error handling triggers correctly on all documented failure modes",
            "Logging captures all required fields to configured destination",
            "Script runs within agreed execution time bounds",
            "Credentials managed via service account or managed identity (no plaintext passwords)",
            "Production execution context configured and first run confirmed successful",
            "Documentation reviewed and approved by client technical contact",
        ],
        "risks": [
            {
                "risk": "Requirements scope creep during development",
                "likelihood": "High",
                "mitigation": "Change order required for any feature addition after requirements sign-off",
            },
            {
                "risk": "API rate limits affecting bulk operations",
                "likelihood": "Medium",
                "mitigation": "Build throttling and retry logic into script scaffold from the start",
            },
            {
                "risk": "Service account permissions insufficient",
                "likelihood": "Medium",
                "mitigation": "Minimum-privilege permissions spec in requirements doc; test in staging first",
            },
            {
                "risk": "Script breaks on future API or schema changes",
                "likelihood": "Low",
                "mitigation": "Version pin API calls where possible; include error notification so failures are visible",
            },
        ],
        "comms_plan": [
            {"trigger": "SOW signed", "action": "Kickoff email + requirements intake sent"},
            {"trigger": "Requirements approved", "action": "Requirements document delivered for sign-off"},
            {"trigger": "Script draft complete", "action": "Internal review notification to Anthony"},
            {"trigger": "Staging run ready", "action": "Staging run notification with review instructions"},
            {"trigger": "Production deployed", "action": "Deployment confirmation email with first-run results"},
            {"trigger": "Day 30", "action": "Health check email"},
        ],
    },

    "firewall-deploy": {
        "name": "Firewall Deployment Project",
        "description": (
            "Firewall deployment or replacement project. Covers Ubiquiti UniFi firewall "
            "deployments, third-party firewall replacements, VLAN segmentation, inter-VLAN "
            "routing policies, site-to-site VPN, and remote access VPN."
        ),
        "timeline_weeks": 3,
        "states": ["SCOPED", "SITE_SURVEY", "DESIGN", "PROCUREMENT", "INSTALLATION", "TESTING", "HANDOFF", "CLOSED"],
        "deliverables": [
            "Site survey and existing network topology map",
            "Firewall design document (VLAN design, ruleset, VPN config, BOM)",
            "Hardware procurement coordination",
            "On-site firewall installation and configuration",
            "Post-installation validation tests vs. acceptance criteria",
            "Network diagram and firewall ruleset documentation",
            "Admin guide (rule management, firmware update procedure)",
            "Final walkthrough call with senior engineer",
            "30-day network health check",
        ],
        "acceptance_criteria": [
            "Internet connectivity verified on all VLANs",
            "Inter-VLAN routing matches approved policy (correct blocks and permits)",
            "Site-to-site VPN established and traffic passing (if in scope)",
            "Remote access VPN working for test user (if in scope)",
            "Firewall rule documentation matches deployed configuration",
            "Firmware updated to latest stable release",
            "Admin credentials rotated and stored in client password manager",
        ],
        "risks": [
            {
                "risk": "Cutover causes internet outage longer than expected",
                "likelihood": "Medium",
                "mitigation": "Pre-stage firewall config; test in lab environment before on-site; rollback = reinstall old hardware",
            },
            {
                "risk": "Application breaks due to new firewall rule gaps",
                "likelihood": "Medium",
                "mitigation": "Application traffic audit during design phase; permissive initial ruleset, then tighten",
            },
            {
                "risk": "ISP modem compatibility issues",
                "likelihood": "Low",
                "mitigation": "Verify ISP device compatibility during site survey",
            },
            {
                "risk": "Hardware delivery delays",
                "likelihood": "Low",
                "mitigation": "Order hardware immediately after design approval; track shipment",
            },
        ],
        "comms_plan": [
            {"trigger": "SOW signed", "action": "Kickoff email + scoping intake sent"},
            {"trigger": "Design approved", "action": "Design document delivered for sign-off"},
            {"trigger": "Hardware ordered", "action": "Order confirmation email with estimated delivery"},
            {"trigger": "Installation day confirmed", "action": "Schedule confirmation with maintenance window details"},
            {"trigger": "Installation complete", "action": "Test results email with network diagram"},
            {"trigger": "Day 30", "action": "Network health check email"},
        ],
    },

    "network-monitoring": {
        "name": "Network Monitoring Setup",
        "description": (
            "Network monitoring deployment project. Covers SNMP monitoring, uptime checks, "
            "bandwidth utilisation alerting, log aggregation, and dashboard configuration "
            "using Atera, PRTG, or equivalent tools. Includes alert threshold tuning and "
            "an escalation runbook."
        ),
        "timeline_weeks": 2,
        "states": ["SCOPED", "SITE_SURVEY", "DESIGN", "INSTALLATION", "TESTING", "HANDOFF", "CLOSED"],
        "deliverables": [
            "Device inventory and monitoring scope document",
            "Monitoring design (tool selection, SNMP community strings, alert thresholds, dashboard layout)",
            "Monitoring agent/sensor deployment on all in-scope devices",
            "Alert threshold configuration and tuning",
            "Escalation runbook (who gets alerted, what to do per alert type)",
            "Dashboard configured and accessible to client",
            "Admin guide (adding devices, adjusting thresholds, interpreting alerts)",
            "Final walkthrough call with senior engineer",
            "30-day noise/tuning check",
        ],
        "acceptance_criteria": [
            "All in-scope devices sending monitoring data with no gaps",
            "Uptime alerts firing correctly (verified by forced test)",
            "Bandwidth alerts triggering at configured thresholds",
            "Dashboard accessible to designated client contacts",
            "Escalation runbook reviewed and approved by client",
            "False-positive rate below 5 alerts/device/week after tuning",
        ],
        "risks": [
            {
                "risk": "SNMP community strings unavailable or firewall-blocked",
                "likelihood": "Medium",
                "mitigation": "Include SNMP access requirements in scoping intake; test during site survey",
            },
            {
                "risk": "Alert noise overwhelming client team",
                "likelihood": "Medium",
                "mitigation": "Start with P1-only alerts; tune thresholds over 30 days before adding P2/P3",
            },
            {
                "risk": "Legacy devices do not support SNMP v2/v3",
                "likelihood": "Low",
                "mitigation": "Identify legacy devices during inventory; use ping/TCP monitoring as fallback",
            },
        ],
        "comms_plan": [
            {"trigger": "SOW signed", "action": "Kickoff email + scoping intake sent"},
            {"trigger": "Design approved", "action": "Monitoring design document delivered for sign-off"},
            {"trigger": "Deployment complete", "action": "Confirmation email with dashboard link"},
            {"trigger": "Day 7 post-deployment", "action": "Noise/tuning check — are alerts useful?"},
            {"trigger": "Day 30", "action": "Monitoring health check + threshold review offer"},
        ],
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    """Convert a company name to a filesystem-safe slug."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def load_yaml_flow(sku: str, project_root: Path) -> Optional[dict]:
    """Try to load the A6_<sku>.yaml state machine for this SKU."""
    if not HAS_YAML:
        return None
    # Map SKU name to expected YAML filename stem
    sku_to_yaml: dict[str, str] = {
        "m365-migration": "A6_m365_migration",
        "azure-project": "A6_azure_project",
        "backup-dr-setup": "A6_backup_dr",
        "intune-rollout": "A6_intune_rollout",
        "windows-server-project": "A6_server_infrastructure",
        "powershell-project": "A6_powershell_automation",
        "firewall-deploy": "A6_network_refresh",
        "network-monitoring": "A6_network_refresh",
    }
    yaml_stem = sku_to_yaml.get(sku)
    if not yaml_stem:
        return None
    yaml_path = project_root / "infra" / "loki-flows" / f"{yaml_stem}.yaml"
    if not yaml_path.exists():
        return None
    try:
        with open(yaml_path) as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"[warn] Could not load {yaml_path}: {e}", file=sys.stderr)
        return None


def build_timeline_table(states: list[str], total_weeks: int, user_count: int) -> str:
    """Build a week-by-week milestone table from states list."""
    # Scale weeks per phase proportionally
    n = len(states)
    if n == 0:
        return ""
    weeks_per_phase = max(1, total_weeks // n)
    remainder = total_weeks - (weeks_per_phase * n)

    lines = ["| Week | Phase | Milestone |", "|------|-------|-----------|"]
    week = 1
    for i, state in enumerate(states):
        extra = 1 if i < remainder else 0
        phase_weeks = weeks_per_phase + extra
        week_range = f"{week}" if phase_weeks == 1 else f"{week}–{week + phase_weeks - 1}"
        milestone = _state_to_milestone(state, user_count)
        lines.append(f"| {week_range} | {state} | {milestone} |")
        week += phase_weeks

    return "\n".join(lines)


def _state_to_milestone(state: str, user_count: int) -> str:
    mapping = {
        "SCOPED": "SOW signed; scoping intake complete; kickoff call held",
        "DISCOVERY": "Environment discovery complete; findings report delivered",
        "DESIGN": f"Architecture/design document approved; plan for {user_count} users confirmed",
        "PILOT": "Pilot environment or pilot group validated",
        "MIGRATION": "Production migration underway; status updates every 2 days",
        "CUTOVER": "Production cutover executed within agreed maintenance window",
        "STABILIZATION": "72-hour stabilisation monitoring complete",
        "HYPERCARE": "72-hour hypercare monitoring complete",
        "CLOSED": "Handoff documentation delivered; walkthrough call complete",
        "INVENTORY": "Asset inventory complete and validated",
        "DEPLOY_BACKUP": "Backup agents deployed to all in-scope systems",
        "DEPLOY_DR": "DR targets configured and replication verified",
        "TEST_FAILOVER": "Failover test executed; RTO/RPO results documented",
        "DOCUMENTED": "Final documentation package reviewed and signed off",
        "TENANT_CONFIG": "Intune tenant configured; MDM authority set",
        "POLICY_DESIGN": "Compliance and configuration policies designed and approved",
        "PILOT_GROUP": "Pilot group enrolled; policies validated; feedback collected",
        "FULL_ROLLOUT": f"Full enrollment of all {user_count} users/devices complete",
        "MONITORING": "7-day compliance monitoring complete",
        "BUILD": "New server environment built and configured",
        "TESTING": "Acceptance tests passed against documented criteria",
        "REQUIREMENTS": "Requirements document signed off",
        "SCRIPT_DEV": "Script development complete; internal review passed",
        "STAGING": "Staging run approved by client",
        "PRODUCTION": "Production deployment confirmed; first run successful",
        "DOCUMENTATION": "Documentation package complete and reviewed",
        "SITE_SURVEY": "Site survey complete; topology map generated",
        "PROCUREMENT": "Hardware ordered; delivery confirmed",
        "INSTALLATION": "Hardware installed and configured at all sites",
        "HANDOFF": "Handoff documentation delivered; walkthrough complete",
    }
    return mapping.get(state, f"{state} phase complete")


def render_plan(
    sku: str,
    client_name: str,
    user_count: int,
    tmpl: dict,
    flow: Optional[dict],
    today: date,
) -> str:
    """Render the markdown project plan."""
    states = tmpl["states"]
    total_weeks = tmpl["timeline_weeks"]

    # Use states from the YAML flow if available (more authoritative)
    if flow and "states" in flow:
        yaml_states = list(flow["states"].keys())
        if yaml_states:
            states = yaml_states

    deliverables_md = "\n".join(f"- {d}" for d in tmpl["deliverables"])
    acceptance_md = "\n".join(f"- {a}" for a in tmpl["acceptance_criteria"])
    risks_md = "\n".join(
        f"| {r['risk']} | {r['likelihood']} | {r['mitigation']} |"
        for r in tmpl["risks"]
    )
    comms_md = "\n".join(
        f"| {c['trigger']} | {c['action']} |"
        for c in tmpl["comms_plan"]
    )
    timeline_md = build_timeline_table(states, total_weeks, user_count)

    flow_note = ""
    if flow:
        flow_note = f"\n> **Workflow engine:** `{flow.get('id', sku)}` — {len(states)}-state machine loaded from `infra/loki-flows/`.\n"

    plan = f"""# Project Plan — {tmpl['name']}
## {client_name}

**Generated:** {today.isoformat()}
**SKU:** `{sku}`
**User count:** {user_count}
**Estimated duration:** {total_weeks} weeks
{flow_note}
---

## 1. Project Scope and Objectives

{tmpl['description']}

This project plan covers all work for **{client_name}** across **{user_count} users**.
All production execution is performed by the Klaravex senior engineer. Loki AI handles
all preparation, documentation, and client communications.

### In scope

{deliverables_md}

### Out of scope

- Any work not listed in the SOW
- Third-party vendor support or licensing procurement (unless explicitly included)
- Ongoing managed support post-project (available via Klaravex managed plans)

---

## 2. Timeline

**Total estimated duration:** {total_weeks} weeks from kickoff call.

{timeline_md}

> Timelines are estimates. Actual duration may vary based on environment complexity,
> client response times, and change order requests. Any scope change requires a signed
> change order before work proceeds.

---

## 3. Deliverables

{deliverables_md}

All deliverables are included in the SOW fixed price unless otherwise noted.

---

## 4. Acceptance Criteria

The project is considered complete when ALL of the following are met:

{acceptance_md}

Acceptance is confirmed in writing by the client primary contact before the final
invoice (if phased billing) is issued.

---

## 5. Risks and Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
{risks_md}

---

## 6. Communications Plan

| Trigger | Action |
|---------|--------|
{comms_md}

**Primary contact (Klaravex):** support@klaravex.com
**Escalation:** Anthony Stewart — available via support@klaravex.com or Loki chat

---

## 7. Change Order Policy

Any work outside the agreed SOW scope requires a signed change order. Loki will halt
work and notify the Klaravex senior engineer when a potential scope deviation is detected.
Change orders are quoted within 1 business day of identification.

---

## 8. Next Steps

1. Client completes scoping intake form (link sent via email)
2. Kickoff call scheduled via Calendly
3. Loki generates milestone schedule and wires it to Anthony's calendar
4. Project begins per the timeline above

---

*This document was generated by Klaravex project-plan-gen.py on {today.isoformat()}.*
*SOW reference: {client_name.replace(' ', '_')}_{sku}_{today.isoformat()}*
"""
    return plan


# ---------------------------------------------------------------------------
# Database insert
# ---------------------------------------------------------------------------

async def insert_ticket(
    client_name: str,
    sku: str,
    user_count: int,
    plan_path: str,
    database_url: str,
) -> Optional[str]:
    """Insert a klaravex_tickets row for this project. Returns the ticket id."""
    if not HAS_ASYNCPG:
        print("[warn] asyncpg not installed — skipping database insert", file=sys.stderr)
        return None
    try:
        conn = await asyncpg.connect(database_url)
        ticket_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO klaravex_tickets
                (id, type, client_name, sku, status, user_count, plan_path,
                 severity, assignee, created_at, updated_at)
            VALUES
                ($1, 'project', $2, $3, 'scoped', $4, $5,
                 'P2', 'loki', NOW(), NOW())
            ON CONFLICT DO NOTHING
            """,
            ticket_id,
            client_name,
            sku,
            user_count,
            plan_path,
        )
        await conn.close()
        return ticket_id
    except Exception as e:
        print(f"[warn] Database insert failed: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate a Klaravex B2B project plan from a SKU template.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--sku",
        required=True,
        choices=list(SKU_TEMPLATES.keys()),
        metavar="SKU",
        help=(
            "Project SKU. One of: "
            + ", ".join(SKU_TEMPLATES.keys())
        ),
    )
    p.add_argument("--client", required=True, help="Client company name")
    p.add_argument("--users", type=int, default=10, help="Number of users (default: 10)")
    p.add_argument("--output", default="plans/", help="Output directory (default: plans/)")
    p.add_argument(
        "--no-db",
        action="store_true",
        help="Skip database insert even if DATABASE_URL is set",
    )
    return p.parse_args()


async def main() -> int:
    args = parse_args()

    sku = args.sku
    client_name = args.client
    user_count = args.users
    output_dir = Path(args.output)
    today = date.today()

    # Locate project root (tools/ is one level down from root)
    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    # Resolve template
    tmpl = SKU_TEMPLATES[sku]

    # Attempt to load the matching A6 YAML
    flow = load_yaml_flow(sku, project_root)
    if flow:
        print(f"[info] Loaded YAML flow: {flow.get('id', sku)}")
    else:
        print(f"[info] No YAML flow found for {sku} — using template defaults")

    # Render the plan
    plan_md = render_plan(sku, client_name, user_count, tmpl, flow, today)

    # Build output filename
    client_slug = slugify(client_name)
    filename = f"{sku}_{client_slug}_{today.isoformat()}.md"

    # Ensure output dir exists
    output_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / filename

    plan_path.write_text(plan_md, encoding="utf-8")
    print(f"[ok] Plan written to {plan_path} ({len(plan_md.splitlines())} lines)")

    # Insert database ticket
    if not args.no_db:
        database_url = os.environ.get("DATABASE_URL")
        if database_url:
            ticket_id = await insert_ticket(
                client_name=client_name,
                sku=sku,
                user_count=user_count,
                plan_path=str(plan_path),
                database_url=database_url,
            )
            if ticket_id:
                print(f"[ok] klaravex_tickets row inserted: {ticket_id}")
            else:
                print("[warn] Database insert skipped or failed — plan file still written")
        else:
            print("[info] DATABASE_URL not set — skipping ticket insert")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
