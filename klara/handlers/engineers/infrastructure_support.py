"""Pillar 6 (website pillar 04) — Infrastructure & Support Engineer.

Owns the **Infrastructure & Support** pillar on klaravex.com end-to-end:
Windows Server / Active Directory, backup & disaster recovery, PowerShell
automation, monitoring & alerting, hardware lifecycle, day-to-day helpdesk
and remote-support delivery.

Mirrors the Vapi assistant "Klaravex Infrastructure & Support"
(id resolved at runtime by name in the squad) so calls Klara or Biz
Engineer route here have a backend reasoning class to dispatch to.
"""
from .base import EngineerAgent


class InfrastructureSupportEngineer(EngineerAgent):
    name = "engineer_infrastructure_support"
    display_name = "Infrastructure & Support Engineer"
    pillar = "infrastructure_support"
    website_anchor = "https://klaravex.com/business/services#infrastructure-support"

    expertise = (
        "Windows Server administration, Active Directory architecture (domain "
        "design, DNS, DHCP, Group Policy, LAPS, tiered admin, hybrid Entra "
        "join), backup & disaster recovery (Veeam, M365 backup, RPO/RTO "
        "definition, test restores, DR runbooks), PowerShell automation "
        "(deployment, reporting, scheduled tasks), endpoint monitoring + "
        "alerting via Atera RMM, patch management SLAs and pilot-group "
        "policy, hardware lifecycle (procurement, refresh cycle, asset "
        "tagging), tier 1/2 helpdesk delivery, and remote-support session "
        "execution via the RustDesk relay."
    )

    system_prompt = (
        "You own the **Infrastructure & Support** pillar at Klaravex. From "
        "klaravex.com (Pillar 04 of 4): the on-prem and hybrid foundation. "
        "Windows Server, Active Directory, backup/DR, automation, monitoring, "
        "hardware, and the day-to-day helpdesk work that keeps clients "
        "running while the other pillars do strategy.\n\n"
        "PRIMARY SCOPE: Windows Server + Active Directory design and "
        "hardening, backup architecture and DR drills, PowerShell automation, "
        "Atera RMM monitoring + alert tuning, patch management policy, "
        "hardware lifecycle, helpdesk SLA delivery, and remote-support "
        "session execution.\n\n"
        "T-SHAPED — you also wear multiple hats and BACK UP these pillars: "
        "Managed Security (you handle the technical patching and backup "
        "controls that show up as SOC 2 CC7 evidence), Microsoft 365 / Cloud "
        "(you handle the hybrid AD-to-Entra sync and the on-prem-to-Azure "
        "migration plumbing). Pull in the pillar owner by name when you "
        "need their specialty.\n\n"
        "OUTPUT QUALITY: name the exact GPO, the exact Veeam job, the exact "
        "PowerShell cmdlet, the exact patch ring. Always include rollback "
        "steps for any change. Never promise the patch won't break "
        "anything — always recommend a pilot ring first. Never claim a "
        "DR plan works until a test restore validates it.\n\n"
        "ABSOLUTE RULES:\n"
        "  - Klaravex provides READINESS ADVISORY only on compliance — for "
        "audit-relevant controls (backup retention, patch SLA), hand to "
        "Regulatory Readiness for the certification framing.\n"
        "  - Never execute changes by voice — your output is always a "
        "draft + ticket for Anthony review. The approval flow exists so "
        "nothing surprises anyone."
    )

    specialty_keywords = [
        "windows server", "server", "active directory", "ad", "domain",
        "dns", "dhcp", "group policy", "gpo", "laps", "kerberos",
        "tiered admin", "hybrid join", "azure ad connect",
        "backup", "veeam", "disaster recovery", "dr", "rto", "rpo",
        "test restore", "failover",
        "powershell", "automation", "scheduled task",
        "atera", "rmm", "monitoring", "alert", "alerting",
        "patch", "patching", "patch ring", "wsus",
        "hardware", "procurement", "refresh cycle", "asset",
        "helpdesk", "tier 1", "tier 2", "ticket follow-up",
        "remote support", "rustdesk", "screen share",
        "computer won't start", "computer wont start",
        "on-site", "onsite", "office it relocation",
    ]
    secondary_keywords = [
        # Managed Security overlap (technical safeguards)
        "edr", "monitoring agent", "endpoint", "encryption", "firewall",
        # M365 overlap (hybrid)
        "entra id", "intune", "azure ad", "m365",
        # Regulatory overlap (evidence)
        "audit log", "evidence", "hipaa", "soc 2",
        # Strategic overlap (capacity / vendor)
        "vendor", "cost", "lifecycle",
    ]
    default_skus = [
        "windows-server-project", "backup-dr-setup", "powershell-project",
        "monitoring-setup", "remote-block-10hr", "remote-block-25hr",
        "office-it-relocation", "procurement-flat",
    ]
    documentation_targets = [
        "Windows Server baseline build (Foundation tier)",
        "Active Directory tiered-admin reference architecture",
        "AD hardening checklist (LAPS, Kerberoasting mitigation, ADCS)",
        "Veeam backup architecture + retention matrix (B2B SMB)",
        "M365-native backup vs Veeam decision tree",
        "Backup validation + quarterly test-restore runbook",
        "DR runbook template (failover + failback)",
        "PowerShell automation library (top 20 MSP scripts)",
        "Atera RMM alert deduplication + escalation policy",
        "Patch management SLA + pilot-ring policy",
        "Hardware lifecycle policy (refresh cycle, asset tagging)",
        "Helpdesk SLA matrix (P1–P4 response + resolution)",
        "Remote-support session execution runbook (RustDesk)",
        "Office IT relocation runbook",
    ]
    # Backups: Infra → M365 (hybrid plumbing) → Managed Security (safeguards)
    backup_pillars = ["microsoft_365", "managed_security"]
