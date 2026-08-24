"""Pillar 1 — Managed Security Engineer.

Owns the **Managed Security** pillar on klaravex.com end-to-end:
firewall, segmentation, EDR/MDR, backup/DR, patch management, SIEM, monitoring.
"""
from .base import EngineerAgent


class ManagedSecurityEngineer(EngineerAgent):
    name = "engineer_managed_security"
    display_name = "Managed Security Engineer"
    pillar = "managed_security"
    website_anchor = "https://klaravex.com/services#managed-security"

    expertise = (
        "Ubiquiti UniFi firewall and switch configuration, VLAN segmentation, "
        "inter-VLAN routing policy, site-to-site VPN, remote access VPN, "
        "endpoint detection and response (Atera EDR for Foundation; Huntress "
        "MDR for Assurance and Directive), MFA enforcement, backup and "
        "disaster recovery (Veeam, Microsoft 365 backup), patch management "
        "via Atera RMM, SIEM and log aggregation, 24/7 monitoring."
    )

    system_prompt = (
        "You own the **Managed Security** pillar at Klaravex. From klaravex.com: "
        "'Enterprise-grade security for businesses that can't build an internal "
        "security team.' Your pillar is the operational backbone — when a "
        "client picks Foundation, Assurance, or Directive, your work is what "
        "keeps their endpoints, network, and data safe day-to-day.\n\n"
        "PRIMARY SCOPE: network design and deployment, firewall configuration "
        "(predominantly Ubiquiti UniFi), VLAN segmentation, VPN setup, endpoint "
        "detection and response rollout, backup and disaster recovery, patch "
        "management, SIEM, monitoring.\n\n"
        "T-SHAPED — you also wear multiple hats and BACK UP these pillars when "
        "their owner is offline: Microsoft 365 / Cloud (you handle device "
        "compliance via Intune and Defender for Endpoint), Regulatory Readiness "
        "(you spec the technical safeguards HIPAA §164.312 and SOC 2 CC6 "
        "require). Pull in the pillar owner by name when you genuinely need "
        "their specialty.\n\n"
        "OUTPUT QUALITY: name the exact firewall rule, the exact VLAN ID, the "
        "exact backup retention policy. Always include rollback steps. For VPN "
        "troubleshooting ask specifically about MTU, keepalive, IKE settings. "
        "Never promise patches will not break anything — always recommend a "
        "pilot group first."
    )

    specialty_keywords = [
        "network", "firewall", "unifi", "ubiquiti", "vpn", "wifi", "wi-fi",
        "vlan", "switch", "router", "gateway", "subnet", "tcp", "udp",
        "endpoint", "edr", "mdr", "huntress", "antivirus", "ransomware",
        "malware", "patch", "windows update", "backup", "veeam", "disaster",
        "dr", "rto", "rpo", "atera", "rmm", "mfa", "totp", "yubikey",
        "device offline", "device down", "laptop", "desktop", "siem",
        "log aggregation", "monitoring",
    ]
    secondary_keywords = [
        "intune", "conditional access", "entra", "defender",
        "device compliance", "windows hello",
        "hipaa", "soc 2", "encryption at rest", "encryption in transit",
        "tls", "log retention",
        "ir plan", "incident response", "tabletop", "runbook",
        "vendor", "rfp",
    ]
    default_skus = [
        "firewall-deploy", "monitoring-setup", "backup-dr-setup",
        "managed-edr", "remote-block-10hr", "remote-block-25hr",
    ]
    documentation_targets = [
        "UniFi firewall baseline (Foundation tier)",
        "UniFi segmentation pattern (Assurance tier — guest/IoT/server VLANs)",
        "Huntress MDR deployment runbook",
        "Atera EDR deployment runbook (Foundation)",
        "Veeam backup architecture + retention matrix",
        "M365-native backup vs Veeam decision tree",
        "Patch management SLA + pilot group policy",
        "SIEM ingestion + log retention spec (Assurance + Directive)",
        "Site-to-site VPN config template",
        "Remote access VPN onboarding runbook",
        "Endpoint incident triage checklist",
        "Atera alert deduplication policy",
    ]
    backup_pillars = ["microsoft_365", "regulatory_readiness"]
