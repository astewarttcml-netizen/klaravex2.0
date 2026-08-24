"""Pillar 3 — Microsoft 365 / Cloud Engineer.

Owns the **Microsoft 365 / Cloud** pillar on klaravex.com end-to-end:
Entra ID, Intune, Defender for Business, Purview, SharePoint/OneDrive,
Secure Score, Google Workspace, AWS.
"""
from .base import EngineerAgent


class Microsoft365Engineer(EngineerAgent):
    name = "engineer_microsoft_365"
    display_name = "Microsoft 365 & Cloud Engineer"
    pillar = "microsoft_365"
    website_anchor = "https://klaravex.com/services#microsoft-365-cloud"

    expertise = (
        "Microsoft 365 administration, Entra ID identity and conditional "
        "access, Intune endpoint management, Microsoft Defender for Office "
        "365 and Defender for Business, Purview data governance + audit log, "
        "Azure AD hybrid sync, SharePoint and OneDrive sharing controls, "
        "Microsoft Secure Score remediation, Copilot deployment foundations, "
        "Google Workspace administration, AWS account hygiene (IAM, "
        "CloudTrail, GuardDuty baseline)."
    )

    system_prompt = (
        "You own the **Microsoft 365 / Cloud** pillar at Klaravex. From "
        "klaravex.com: 'Microsoft 365 depth — Entra ID architecture, Purview "
        "data governance, Defender for Business, Copilot deployment — the "
        "full tenant, hardened.' Your pillar is the productivity + identity "
        "foundation under every client engagement.\n\n"
        "PRIMARY SCOPE: tenant setup, migration, hardening, Entra ID "
        "conditional access policies, Intune device compliance, Defender for "
        "Office 365 Safe Links and Safe Attachments, Defender for Business, "
        "Purview DLP and audit log, SharePoint and OneDrive sharing controls, "
        "Microsoft Secure Score remediation. Also Google Workspace and AWS "
        "baseline hygiene when those are the client's stack.\n\n"
        "T-SHAPED — you also wear multiple hats and BACK UP these pillars: "
        "Managed Security (you handle Intune device compliance + Defender), "
        "AI Adoption (you stand up the M365 Copilot tenant prerequisites). "
        "Pull in the pillar owner by name when you genuinely need their "
        "specialty.\n\n"
        "OUTPUT QUALITY: name the exact policy, name the exact CSP setting, "
        "name the exact PowerShell cmdlet or Graph API call. Avoid vague "
        "advice. Always include a rollback plan for any configuration change. "
        "Never claim a configuration certifies the tenant compliant — "
        "Klaravex provides readiness advisory, not certifications."
    )

    specialty_keywords = [
        "m365", "microsoft 365", "office 365", "office365", "o365",
        "outlook", "exchange", "exchange online", "teams", "sharepoint",
        "onedrive", "entra", "entra id", "azure ad", "aad",
        "intune", "endpoint manager", "mdm", "defender", "purview",
        "secure score", "conditional access", "ca policy", "mfa",
        "autopilot", "azure", "graph api", "powershell", "azure portal",
        "google workspace", "gworkspace", "gsuite",
        "aws", "iam", "cloudtrail", "guardduty",
    ]
    secondary_keywords = [
        "endpoint", "device", "windows", "mac", "patch", "patching",
        "antivirus", "edr", "compliance baseline",
        "hipaa", "soc 2", "iso 27001", "purview audit log", "dlp",
        "evidence", "control",
        "copilot", "license", "e3", "e5", "business premium",
        "cost", "roadmap",
    ]
    default_skus = [
        "m365-setup", "m365-migration", "intune-rollout", "azure-review",
        "azure-project",
    ]
    documentation_targets = [
        "M365 tenant baseline hardening (Secure Score 80+)",
        "Entra ID Conditional Access policy library",
        "Intune device compliance baseline (Windows + macOS + iOS + Android)",
        "Defender for Business deployment runbook",
        "Defender for Office 365 Safe Links + Safe Attachments policy",
        "Purview audit log retention + eDiscovery setup",
        "Purview DLP policy starter set",
        "SharePoint + OneDrive external sharing governance",
        "M365 tenant migration runbook (cutover + staged)",
        "M365 license rightsizing decision matrix (BP / E3 / E5)",
        "Copilot for M365 prerequisite checklist (handoff to AI Adoption)",
        "Google Workspace baseline hardening",
        "AWS account baseline (IAM + CloudTrail + GuardDuty)",
        "Tenant rollback procedure for failed CA policy",
    ]
    backup_pillars = ["managed_security", "ai_adoption"]
