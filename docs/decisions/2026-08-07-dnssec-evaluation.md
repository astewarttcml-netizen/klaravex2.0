# DNSSEC Evaluation — klaravex.com & personal.klaravex.com

**Date:** 2026-08-07
**Reference:** LAUNCH-READINESS-TASKS.md L27, Cowbell flag G26
**Status:** Decision documented — deferred, enable post-launch

---

## 1. Current State

| | klaravex.com | personal.klaravex.com |
|---|---|---|
| **Registrar** | Hosting Concepts B.V. d/b/a Registrar.eu (Openprovider reseller) | Same |
| **DNS Provider** | Azure DNS (ns1-03.azure-dns.com through ns4-03.azure-dns.info) | Azure DNS (same nameserver set) |
| **DNSSEC (WHOIS)** | unsigned | unsigned |
| **DS records at parent** | None | None |
| **DNSKEY records** | None (DNSSEC not enabled in Azure zone) | None |

Both domains share the same registrar and DNS infrastructure. Neither has any DNSSEC configuration.

---

## 2. Technical Feasibility

### Azure DNS DNSSEC
Azure DNS has supported DNSSEC as a **Generally Available** feature since late 2024. When enabled on a zone:
- Azure automatically generates and manages both ZSK and KSK keys.
- Azure handles automatic key rollover on a schedule.
- The portal/CLI surfaces the DS record set that must be submitted to the registrar.
- **Azure does NOT submit DS records to the registrar automatically** — that step is manual.

### Registrar Support (Openprovider / Registrar.eu)
Openprovider supports DNSSEC DS record management for domains delegated to third-party DNS providers. The workflow:
1. Enable DNSSEC signing in Azure DNS.
2. Copy the DS record values from the Azure portal.
3. Submit those DS records via the Openprovider control panel (or API).
4. Wait for parent-zone propagation (typically minutes to hours).
5. Validate with DNSSEC checker tools.

Both layers support the operation — there are no blocking technical gaps.

---

## 3. Risk Assessment

### Failure modes
| Failure | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **Wrong DS record submitted to registrar** | Medium (manual copy step) | **High** — domain unresolvable by validating resolvers | Copy-paste from Azure portal; validate with DNSViz/DNSSEC Analyzer before and after |
| **Key rollover mishap** | Low (Azure manages rotation automatically) | High | Azure handles ZSK/KSK rotation; DS record stays valid across rollovers |
| **Zone signing breaks after DNS changes** | Very low (Azure managed service) | Medium | Azure DNS is a managed service; signing is transparent once enabled |
| **Registrar expires / loses DS records** | Very low | Medium | DS records are persisted in the registry; not dependent on registrar staying online |

### Biggest risk
The single point of failure is the **manual DS record submission step at Openprovider**. If the wrong values are pasted, DNSSEC-aware resolvers (Google Public DNS, Cloudflare, Quad9, Comcast) will reject all responses for the domain. This is a self-inflicted outage that takes effect within the DS TTL (typically 1 hour) and is immediately visible to all DNSSEC-validating clients.

However, this risk is **one-time at setup** — once the correct DS records are in the parent zone, Azure's automated key management means there is no ongoing manual intervention required.

### Reversibility
DNSSEC can be disabled in Azure DNS and DS records removed at the registrar to fully revert. Rollback takes effect within DS TTL. No data loss, no configuration drift.

---

## 4. Effort Estimate

| Step | Time |
|---|---|
| Enable DNSSEC signing on klaravex.com Azure DNS zone | 2 min (portal) or 1 CLI command |
| Enable DNSSEC signing on personal.klaravex.com Azure DNS zone | 2 min |
| Copy DS records from Azure portal | 2 min |
| Submit DS records via Openprovider control panel | 5 min |
| Wait for parent-zone propagation + validate | 15–60 min (mostly waiting) |
| **Total active effort** | **~15 minutes** |
| **Total wall-clock (with validation)** | **~1 hour** |

No infrastructure changes, no code changes, no deployment required.

---

## 5. Decision

**Defer DNSSEC to post-launch.**

### Rationale
1. **Low urgency for launch.** Neither domain has been targeted by DNS spoofing attacks. DNSSEC is a hardening measure, not a launch blocker.
2. **B2B MSP trust signal deferred to growth phase.** klaravex.com serves security-conscious B2B buyers who may check for DNSSEC as a trust signal, but this matters more once outbound campaigns are running and prospects are actively evaluating the brand. The current priority is getting the sites live and complete.
3. **One-time setup risk during launch window is unnecessary.** The DS record submission step, while simple, introduces a non-zero risk of a self-inflicted DNS outage. This should not be done in the same window as other DNS changes (L23 cache discipline, L22 DMARC rua, etc.).
4. **Azure DNS makes this a low-effort, low-risk operation once the launch dust settles.** No ongoing key ceremonies, no cron jobs, no custom tooling.

### Recommendation
- **Enable for klaravex.com** as part of the post-launch hardening sprint (after L22 DMARC rua and L24 xmlrpc.php are resolved).
- **Defer personal.klaravex.com** indefinitely — the personal brand site gains negligible security benefit from DNSSEC.
- When enabling: schedule during a low-traffic window, validate with DNSViz, and keep the Azure portal open for immediate rollback if validation fails.

### Activation checklist (for when the time comes)
1. [ ] Enable DNSSEC signing on klaravex.com Azure DNS zone.
2. [ ] Copy the 4 DS records (KSK + ZSK, SHA-256 + SHA-384) from Azure portal.
3. [ ] Submit DS records via Openprovider control panel.
4. [ ] Wait 5 minutes for parent-zone propagation.
5. [ ] Validate: `dig klaravex.com DS +short` returns records.
6. [ ] Validate: [DNSViz](https://dnsviz.net/) shows green chain for klaravex.com.
7. [ ] Validate: `dig klaravex.com A +dnssec` returns RRSIG records with `ad` flag.
8. [ ] Monitor klaravex.com resolution from multiple vantage points for 24 hours.

---

## 6. References
- [Azure DNS DNSSEC overview](https://learn.microsoft.com/en-us/azure/dns/dnssec)
- [Openprovider DNSSEC for third-party DNS](https://support.openprovider.eu/hc/en-us/articles/360010899380)
- LAUNCH-READINESS-TASKS.md L27, L22 (DMARC rua), L24 (xmlrpc.php)
- WHOIS: both domains `DNSSEC: unsigned` via Registrar.eu (IANA 1647)
