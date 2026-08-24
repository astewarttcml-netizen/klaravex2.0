"""
app/agents/task_automator.py
──────────────────────────────
TaskAutomatorAgent — P3 service-delivery agent.

Matches an incoming support request to a pre-defined playbook and generates
a tailored, tenant-specific execution checklist (with exact PowerShell /
Graph API commands substituted) for Anthony to review before execution.

Trigger:  POST /api/v1/admin/automation/run-playbook

Input data:
  request_type      (str)  — one of the five supported playbook keys
  tenant_id         (str)  — Azure / M365 tenant ID
  client_name       (str)  — client display name
  target_user_upn   (str, optional)  — UPN for user-scoped tasks
  additional_context (dict, optional) — arbitrary extra data passed to Claude

Supported request_type values:
  "mfa_reset"            — Reset a user's MFA methods
  "new_hire_m365"        — Provision a new M365 user
  "offboarding"          — Offboard a departing user
  "m365_tenant_baseline" — Apply CIS M365 baseline hardening to a tenant
  "meraki_vlan_setup"    — Configure a new VLAN on a Meraki network

Flow:
  1. Validate request_type and required fields per playbook.
  2. Select playbook template and inject context into Claude prompt.
  3. Claude generates tenant-specific checklist with exact commands, pre-flight
     checks, rollback steps, and verification commands.
  4. Create ApprovalRequest (P3) via approval_manager.
  5. Write AuditLog entry.
  6. Return AgentResult.needs_approval() with checklist in approval payload.

Permission: P3 — client environment changes require Anthony's sign-off.
"""
from __future__ import annotations

import json

import structlog
from anthropic import AsyncAnthropic

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.core.permissions import PermissionLevel

logger = structlog.get_logger(__name__)

# ── Playbook templates ────────────────────────────────────────────────────────
# Each value is a dict with:
#   description  — one-liner shown in the approval justification
#   requires_upn — whether target_user_upn is mandatory
#   prompt_body  — instructions passed to Claude (tenant/user context injected at runtime)

_PLAYBOOKS: dict[str, dict] = {
    "mfa_reset": {
        "description": "Reset all MFA methods for a user account in Entra ID",
        "requires_upn": True,
        "prompt_body": """\
Generate a step-by-step execution checklist to reset all MFA authentication methods
for user {target_user_upn} in tenant {tenant_id} ({client_name}).

The checklist must include these sections in order:

### Pre-flight Checks
- Confirm the user account exists and is not already disabled:
  Get-MgUser -UserId "{target_user_upn}" | Select-Object DisplayName,AccountEnabled,Id
- Verify the operator has at least Authentication Administrator role:
  Get-MgRoleManagementDirectoryRoleAssignment -Filter "principalId eq '<your-object-id>'"

### Execution Steps
1. Connect to Microsoft Graph (PowerShell):
   Connect-MgGraph -TenantId "{tenant_id}" -Scopes "UserAuthenticationMethod.ReadWrite.All"
2. List all current authentication methods:
   Get-MgUserAuthenticationMethod -UserId "{target_user_upn}"
3. Remove each method type individually (list exact cmdlets for):
   - Microsoft Authenticator app (softwareOath / microsoftAuthenticator)
   - TOTP hardware token (softwareOath)
   - Phone (SMS/voice): Remove-MgUserAuthenticationPhoneMethod
   - Email OTP:         Remove-MgUserAuthenticationEmailMethod
   - FIDO2 key:         Remove-MgUserAuthenticationFido2Method
   - Temporary Access Pass: Remove-MgUserAuthenticationTemporaryAccessPassMethod
4. If MFA must be immediately re-enabled, issue a Temporary Access Pass:
   New-MgUserAuthenticationTemporaryAccessPassMethod -UserId "{target_user_upn}" \\
     -IsUsableOnce $false -LifetimeInMinutes 480

### Rollback Steps
- MFA methods cannot be re-added on behalf of the user once deleted.
- Rollback = issue TAP immediately and ask user to re-register.
- Document deletion timestamp in the client's ticketing system.

### Verification
- Confirm methods list is empty (or only contains TAP if issued):
  Get-MgUserAuthenticationMethod -UserId "{target_user_upn}"
- Check sign-in logs for any anomalous activity during the reset window:
  Get-MgAuditLogSignIn -Filter "userPrincipalName eq '{target_user_upn}'" -Top 10

### Mandatory Post-Steps
- Notify the user via a secondary channel (phone or manager) that MFA has been reset.
- Log the change in the client's IT change log with operator name, timestamp, and ticket ID.
""",
    },

    "new_hire_m365": {
        "description": "Provision a new M365 user account for a new employee",
        "requires_upn": True,
        "prompt_body": """\
Generate a step-by-step checklist to provision a new Microsoft 365 user
with UPN {target_user_upn} in tenant {tenant_id} ({client_name}).

The checklist must include these sections in order:

### Pre-flight Checks
- Verify UPN availability:
  Get-MgUser -Filter "userPrincipalName eq '{target_user_upn}'" — must return null
- Confirm an M365 licence is available:
  Get-MgSubscribedSku | Select-Object SkuPartNumber,ConsumedUnits,@{{N='Available';E={{$_.PrepaidUnits.Enabled - $_.ConsumedUnits}}}}
- Confirm manager UPN exists and is licensed

### Execution Steps
1. Connect:
   Connect-MgGraph -TenantId "{tenant_id}" \\
     -Scopes "User.ReadWrite.All","Directory.ReadWrite.All","UserAuthenticationMethod.ReadWrite.All"
2. Create user:
   $params = @{{
     DisplayName = "<FirstName LastName>"
     UserPrincipalName = "{target_user_upn}"
     MailNickname = "<alias>"
     AccountEnabled = $true
     PasswordProfile = @{{
       ForceChangePasswordNextSignIn = $true
       Password = "<16-char random generated by operator>"
     }}
     UsageLocation = "DE"
   }}
   New-MgUser @params
3. Assign M365 licence (substitute SkuId from pre-flight step):
   Set-MgUserLicense -UserId "{target_user_upn}" \\
     -AddLicenses @{{SkuId="<sku-id>"}} -RemoveLicenses @()
4. Set manager:
   $mgr = Get-MgUser -Filter "userPrincipalName eq '<manager-upn>'"
   Set-MgUserManagerByRef -UserId "{target_user_upn}" \\
     -AdditionalProperties @{{"@odata.id"="https://graph.microsoft.com/v1.0/users/$($mgr.Id)"}}
5. Add to required security groups (list groups per client standard):
   New-MgGroupMember -GroupId "<group-id>" -DirectoryObjectId (Get-MgUser -UserId "{target_user_upn}").Id
6. Issue Temporary Access Pass for first sign-in:
   New-MgUserAuthenticationTemporaryAccessPassMethod -UserId "{target_user_upn}" \\
     -IsUsableOnce $false -LifetimeInMinutes 480

### Rollback Steps
- Disable account if error during provisioning:
  Update-MgUser -UserId "{target_user_upn}" -AccountEnabled $false
- Remove licence to avoid billing:
  Set-MgUserLicense -UserId "{target_user_upn}" -RemoveLicenses @("<sku-id>") -AddLicenses @()
- Delete user (only if never activated):
  Remove-MgUser -UserId "{target_user_upn}"

### Verification
- Confirm user exists and is licensed:
  Get-MgUser -UserId "{target_user_upn}" | Select-Object DisplayName,AccountEnabled,AssignedLicenses
- Confirm manager set:
  Get-MgUserManager -UserId "{target_user_upn}" | Select-Object DisplayName
- Confirm TAP exists:
  Get-MgUserAuthenticationMethod -UserId "{target_user_upn}"
""",
    },

    "offboarding": {
        "description": "Offboard a departing user: revoke access, preserve data, disable account",
        "requires_upn": True,
        "prompt_body": """\
Generate a comprehensive offboarding checklist for user {target_user_upn}
in tenant {tenant_id} ({client_name}).

The checklist must include these sections in order:

### Pre-flight Checks
- Confirm the user exists and is currently enabled:
  Get-MgUser -UserId "{target_user_upn}" | Select-Object DisplayName,AccountEnabled,LastPasswordChangeDateTime
- Check for any active licence assignments to be removed
- Verify no active shared mailbox delegation already exists

### Phase 1 — Immediate Actions (execute within 1 hour of departure confirmation)
1. Revoke all active sessions and tokens:
   Revoke-MgUserSignInSession -UserId "{target_user_upn}"
2. Reset password to a long random string (prevents re-auth with cached creds):
   Update-MgUser -UserId "{target_user_upn}" \\
     -PasswordProfile @{{ForceChangePasswordNextSignIn=$true; Password="<32-char random>"}}
3. Disable the account:
   Update-MgUser -UserId "{target_user_upn}" -AccountEnabled $false
4. Remove from all security groups (enumerate first):
   Get-MgUserMemberOf -UserId "{target_user_upn}" | ForEach-Object {{
     Remove-MgGroupMemberByRef -GroupId $_.Id \\
       -DirectoryObjectId (Get-MgUser -UserId "{target_user_upn}").Id
   }}
5. Remove all MFA authentication methods (use mfa_reset playbook steps).

### Phase 2 — Data Preservation (within 24 hours)
6. Convert mailbox to shared mailbox (preserves email without consuming a licence):
   Set-Mailbox -Identity "{target_user_upn}" -Type Shared
7. Grant manager access to shared mailbox:
   Add-MailboxPermission -Identity "{target_user_upn}" \\
     -User "<manager-upn>" -AccessRights FullAccess -InheritanceType All
8. Set auto-reply (OOF) on the mailbox to inform senders.
9. Transfer OneDrive ownership to manager (30-day grace, then auto-deleted):
   In SharePoint Admin Centre → Active Sites → locate user's OneDrive →
   set secondary admin to manager UPN.

### Phase 3 — Licence and Billing (within 48 hours)
10. Remove all assigned licences:
    Set-MgUserLicense -UserId "{target_user_upn}" -RemoveLicenses @("<sku-ids>") -AddLicenses @()

### Rollback Steps
- Rollback is intentionally limited — offboarding is a one-way process.
- If actioned in error: re-enable account, reset to TAP, re-assign licences.
- Restore group memberships from the change log.

### Verification
- Account disabled: Get-MgUser -UserId "{target_user_upn}" | Select-Object AccountEnabled
- No active sessions: confirmed by 0 results in sign-in logs after revocation
- Shared mailbox set: Get-Mailbox "{target_user_upn}" | Select-Object RecipientTypeDetails
- Licences removed: Get-MgUser -UserId "{target_user_upn}" | Select-Object AssignedLicenses
""",
    },

    "m365_tenant_baseline": {
        "description": "Apply CIS Microsoft 365 Foundations Benchmark v3.1 baseline to a tenant",
        "requires_upn": False,
        "prompt_body": """\
Generate an M365 tenant baseline hardening checklist for tenant {tenant_id}
({client_name}) aligned to CIS Microsoft 365 Foundations Benchmark v3.1.

The checklist must include these sections in order:

### Pre-flight Checks
- Confirm Global Administrator access:
  Connect-MgGraph -TenantId "{tenant_id}" -Scopes "Directory.ReadWrite.All","Policy.ReadWrite.All"
  Get-MgContext | Select-Object Account,TenantId,Scopes
- Export current baseline for rollback reference:
  Invoke-RestMethod -Uri "https://graph.microsoft.com/v1.0/policies/identitySecurityDefaultsEnforcementPolicy" \\
    -Headers @{{Authorization="Bearer $(Get-MgAccessToken)"}} | ConvertTo-Json | Out-File baseline_before.json

### CIS Control Sections to Apply

#### 1. Authentication (CIS 1.x)
1.1 Enable Security Defaults OR configure equivalent Conditional Access policies.
    Security Defaults (quick path):
    $params = @{{"isEnabled" = $true}}
    Invoke-MgGraphRequest -Method PATCH \\
      -Uri "/v1.0/policies/identitySecurityDefaultsEnforcementPolicy" -Body $params
1.2 Ensure MFA is enforced for all admin accounts (CA policy or Security Defaults).
1.3 Disable legacy authentication protocols:
    New-MgIdentityConditionalAccessPolicy with conditions.clientAppTypes = ["exchangeActiveSync","other"]
    and grantControls.builtInControls = ["block"].
1.4 Ensure no users have permanent Global Administrator assignment — use PIM.

#### 2. Application Permissions (CIS 2.x)
2.1 Restrict user consent to apps:
    Update-MgPolicyAuthorizationPolicy -DefaultUserRolePermissions \\
      @{{AllowedToCreateApps=$false}} — also set tenant consent policy to "Allow verified publishers only"
2.2 Review and remove unused OAuth app consents:
    Get-MgServicePrincipal -Filter "tags/any(t:t eq 'WindowsAzureActiveDirectoryIntegratedApp')"

#### 3. Data Management (CIS 3.x)
3.1 Enable Microsoft Purview DLP policies for sensitive data types (PII, financial).
3.2 Configure retention policies for Exchange, SharePoint, OneDrive (minimum 1 year).
3.3 Enable sensitivity labels for email and documents.

#### 4. Email Security (CIS 4.x)
4.1 Verify SPF, DKIM, and DMARC are configured for all accepted domains.
    Get-AcceptedDomain | ForEach {{ Resolve-DnsName -Name "_dmarc.$($_.Name)" -Type TXT }}
4.2 Enable EOP anti-phishing policy with impersonation protection enabled.
4.3 Enable Safe Links and Safe Attachments (Defender for Office 365 Plan 1 minimum).

#### 5. Audit and Alerting (CIS 5.x)
5.1 Enable Unified Audit Log:
    Set-AdminAuditLogConfig -UnifiedAuditLogIngestionEnabled $true
5.2 Set audit log retention to 90 days minimum (1 year for M365 E3+).
5.3 Configure alert policies for: impossible travel, mass file deletion, malware detected.

#### 6. SharePoint and Teams (CIS 6.x)
6.1 Restrict SharePoint external sharing to existing guests or specific domains only.
    Set-SPOTenant -SharingCapability ExternalUserSharingOnly
6.2 Restrict Teams guest access to approved domains only.
6.3 Disable anonymous meeting join or restrict to lobby.

### Rollback Steps
- Restore Security Defaults state from baseline_before.json.
- CA policies can be set to Report-Only mode before switching to Enabled.
- SharePoint external sharing can be reverted via Set-SPOTenant.
- Document each change with timestamp and operator in the change log.

### Verification
- Run Maester baseline check (open source):
  Install-Module Maester; Connect-Maester -TenantId "{tenant_id}"; Invoke-Maester
- Review Microsoft Secure Score before/after (target: improvement of ≥10 points).
- Confirm Unified Audit Log enabled: Get-AdminAuditLogConfig | Select-Object UnifiedAuditLogIngestionEnabled
""",
    },

    "meraki_vlan_setup": {
        "description": "Configure a new VLAN on a Meraki network with firewall rules and DHCP",
        "requires_upn": False,
        "prompt_body": """\
Generate a step-by-step checklist to configure a new VLAN on a Meraki network
for client {client_name}.

Use the additional context provided: {additional_context_json}

The checklist must include these sections in order:

### Pre-flight Checks
- Confirm API access and retrieve network list:
  GET https://api.meraki.com/api/v1/organizations/<org-id>/networks
  Header: X-Cisco-Meraki-API-Key: <api-key>
- Verify the target VLAN ID is not already in use:
  GET https://api.meraki.com/api/v1/networks/<network-id>/appliance/vlans
- Confirm the MX appliance firmware supports VLANs (MX 15.x+).
- Confirm switch port count is sufficient for the new segment.

### Execution Steps

#### Step 1 — Create the VLAN (Meraki Dashboard API)
POST https://api.meraki.com/api/v1/networks/<network-id>/appliance/vlans
Body:
{{
  "id": <vlan-id>,
  "name": "<vlan-name>",
  "subnet": "<subnet-cidr>",
  "applianceIp": "<gateway-ip>"
}}

#### Step 2 — Configure DHCP on the VLAN
PUT https://api.meraki.com/api/v1/networks/<network-id>/appliance/vlans/<vlan-id>
Body:
{{
  "dhcpHandling": "Run a DHCP server",
  "dhcpLeaseTime": "12 hours",
  "dhcpBootOptionsEnabled": false,
  "dnsNameservers": "upstream_dns",
  "dhcpOptions": [],
  "reservedIpRanges": [],
  "fixedIpAssignments": {{}}
}}

#### Step 3 — Assign Switch Ports to VLAN
For each access port carrying this VLAN:
PUT https://api.meraki.com/api/v1/devices/<switch-serial>/switch/ports/<port-id>
Body:
{{
  "type": "access",
  "vlan": <vlan-id>,
  "stpGuard": "bpdu guard"
}}

#### Step 4 — Apply Firewall Rules (L3 — MX appliance)
GET current rules first to avoid overwriting:
GET https://api.meraki.com/api/v1/networks/<network-id>/appliance/firewall/l3FirewallRules
Prepend new rules and PUT the full array back.
Minimum rules for a new VLAN:
  - ALLOW: new VLAN → internet (port any)
  - DENY:  new VLAN → management VLAN (unless this IS the management VLAN)
  - DENY:  new VLAN → any other internal VLAN (default deny lateral)

#### Step 5 — Verify Connectivity
- Ping test from a device in the new VLAN to the gateway IP.
- Confirm DHCP lease issued: check Dashboard → Network-wide → Clients.
- Confirm internet access from a test device.
- Confirm intra-VLAN firewall rules are enforced (attempt blocked connection).

### Rollback Steps
- Remove VLAN:
  DELETE https://api.meraki.com/api/v1/networks/<network-id>/appliance/vlans/<vlan-id>
- Revert switch ports to previous VLAN assignment (restore from pre-flight backup).
- Restore firewall rules from the pre-flight GET snapshot.

### Verification
- VLAN exists: GET /networks/<network-id>/appliance/vlans — confirm new VLAN in list.
- DHCP working: check Meraki Dashboard → Clients for new VLAN leases.
- Firewall rules in place: GET /networks/<network-id>/appliance/firewall/l3FirewallRules.
""",
    },
}


class TaskAutomatorAgent(BaseAgent):
    name = "task_automator"
    description = (
        "Matches a support request to a playbook and generates a tailored, "
        "tenant-specific execution checklist with exact PowerShell/Graph API commands. "
        "Supported: mfa_reset, new_hire_m365, offboarding, m365_tenant_baseline, "
        "meraki_vlan_setup. Creates P3 ApprovalRequest before execution. "
        "Trigger: POST /api/v1/admin/automation/run-playbook."
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
        request_type: str = (input_data.get("request_type") or "").strip().lower()
        tenant_id: str = (input_data.get("tenant_id") or "").strip()
        client_name: str = (input_data.get("client_name") or "").strip()
        target_user_upn: str = (input_data.get("target_user_upn") or "").strip()
        additional_context: dict = input_data.get("additional_context") or {}

        if not request_type:
            return AgentResult.fail(
                "task_automator: 'request_type' is required.",
                agent=self.name,
            )

        if request_type not in _PLAYBOOKS:
            return AgentResult.fail(
                f"task_automator: unknown request_type '{request_type}'. "
                f"Supported: {', '.join(sorted(_PLAYBOOKS))}.",
                agent=self.name,
            )

        if not tenant_id:
            return AgentResult.fail(
                "task_automator: 'tenant_id' is required.",
                agent=self.name,
            )

        if not client_name:
            return AgentResult.fail(
                "task_automator: 'client_name' is required.",
                agent=self.name,
            )

        playbook = _PLAYBOOKS[request_type]

        if playbook["requires_upn"] and not target_user_upn:
            return AgentResult.fail(
                f"task_automator: 'target_user_upn' is required for "
                f"request_type '{request_type}'.",
                agent=self.name,
            )

        log.info(
            "task_automator.generating",
            request_type=request_type,
            client_name=client_name,
            tenant_id=tenant_id,
            target_user_upn=target_user_upn or "(not applicable)",
        )

        # ── Build Claude prompt ───────────────────────────────────────────────
        prompt_body = playbook["prompt_body"].format(
            target_user_upn=target_user_upn or "(not applicable)",
            tenant_id=tenant_id,
            client_name=client_name,
            additional_context_json=json.dumps(additional_context, indent=2),
        )

        full_prompt = (
            "You are a senior Microsoft and Cisco Meraki engineer at Klaravex.\n"
            "Generate a production-ready execution checklist based on the following instructions.\n"
            "Use ### for subsection headings. Use code blocks (``` powershell or ``` bash) for "
            "all commands. Include exact parameter values where context provides them; use "
            "<placeholder> syntax where the operator must supply a value.\n"
            "Output ONLY the checklist in Markdown — no preamble, no explanation outside the document.\n\n"
            + prompt_body
        )

        # ── Call Claude ───────────────────────────────────────────────────────
        anthropic_client = AsyncAnthropic(api_key=context.settings.anthropic_api_key)
        try:
            response = await anthropic_client.messages.create(
                model=context.settings.anthropic_model,
                max_tokens=context.settings.anthropic_max_tokens,
                messages=[{"role": "user", "content": full_prompt}],
            )
            try:
                from app.services.llm_cost import track_response
                await track_response(
                    context.db, agent_name=self.name,
                    model=context.settings.anthropic_model,
                    response=response, lead_id=getattr(context, 'lead_id', None),
                )
            except Exception:
                pass
            checklist_markdown: str = response.content[0].text.strip()
            tokens_used: int = response.usage.output_tokens
        except Exception as exc:
            log.error(
                "task_automator.claude_error",
                error=str(exc),
                exc_info=True,
            )
            try:
                await db.rollback()
            except Exception:
                pass
            return AgentResult.fail(
                f"task_automator: LLM error — {exc}",
                agent=self.name,
            )

        log.info(
            "task_automator.checklist_generated",
            request_type=request_type,
            tokens_used=tokens_used,
            doc_length=len(checklist_markdown),
        )

        # ── Create P3 ApprovalRequest ─────────────────────────────────────────
        approval_payload = {
            "request_type": request_type,
            "tenant_id": tenant_id,
            "client_name": client_name,
            "target_user_upn": target_user_upn or None,
            "additional_context": additional_context,
            "checklist_markdown": checklist_markdown,
            "playbook_description": playbook["description"],
        }

        try:
            from app.agents.registry import registry
            approval_mgr = registry.get("approval_manager")
            approval_result = await approval_mgr(
                context,
                {
                    "action": "create",
                    "action_name": f"task_automator.{request_type}",
                    "risk_level": "P3",
                    "payload": approval_payload,
                    "justification": (
                        f"Execution checklist generated: {playbook['description']} — "
                        f"client {client_name} (tenant {tenant_id})"
                        + (f", user {target_user_upn}" if target_user_upn else "")
                        + ". Review before executing against production tenant."
                    ),
                    "requested_by": self.name,
                },
            )
        except Exception as exc:
            log.error(
                "task_automator.approval_queue_error",
                error=str(exc),
                exc_info=True,
            )
            try:
                await db.rollback()
            except Exception:
                pass
            return AgentResult.fail(
                f"task_automator: approval queue error — {exc}",
                agent=self.name,
            )

        if not approval_result.success:
            return AgentResult.fail(
                f"task_automator: could not create approval request — "
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
                    "action_name": f"task_automator.{request_type}",
                    "lead_id": context.lead_id,
                    "approval_id": approval_id,
                    "details": {
                        "request_type": request_type,
                        "client_name": client_name,
                        "tenant_id": tenant_id,
                        "target_user_upn": target_user_upn or None,
                        "tokens_used": tokens_used,
                        "status": "pending_approval",
                    },
                    "success": True,
                },
            )
        except Exception as exc:
            log.warning("task_automator.audit_warning", error=str(exc))

        log.info(
            "task_automator.queued_for_approval",
            approval_id=approval_id,
            request_type=request_type,
            client_name=client_name,
        )

        return AgentResult.needs_approval(
            approval_id=approval_id,
            action=f"task_automator.{request_type}",
        )
