# Dispatch artifacts — 2026-06-18

24 tasks (+1 dup `T14.7`) sent through LiteLLM proxy across 4 models. Each
artifact below is a draft. Routing legend:

- **doc-staging** — customer/internal markdown; drop into `drafts/`, ship verbatim or refine
- **commit-target** — code/config change; can be applied as a commit
- **spec** — implementation spec needing a follow-up build

| id | model | bucket | target | first-line |
|---|---|---|---|---|
| `AC-VERIFY` | claude-sonnet | doc-staging | `drafts/dispatch-2026-06-18/AC-VERIFY.md` | AC-VERIFY — End-to-End Outbound Pipeline Verificat |
| `G34.1` | qwen-72b | doc-staging | `drafts/dispatch-2026-06-18/G34.1.md` | Task ID: G34.1 - RustDesk Transport Binding - Pick |
| `PH12.V10` | qwen-72b | doc-staging | `drafts/dispatch-2026-06-18/PH12.V10.md` | Phase12-TESTING-INSTRUCTIONS.md |
| `PH12.V12` | qwen-72b | doc-staging | `drafts/dispatch-2026-06-18/PH12.V12.md` | VIP Backend API Implementation Spec |
| `PH12.V13` | qwen-72b | doc-staging | `drafts/dispatch-2026-06-18/PH12.V13.md` | Implementation Specification for Task ID: PH12.V13 |
| `PH12.V14` | qwen-72b | doc-staging | `drafts/dispatch-2026-06-18/PH12.V14.md` | VIP Test Scenarios for Phase 12 |
| `PH12.V8` | qwen-72b | doc-staging | `drafts/dispatch-2026-06-18/PH12.V8.md` | Implementation Specification for Task ID: PH12.V8 |
| `PH12.V9` | qwen-72b | doc-staging | `drafts/dispatch-2026-06-18/PH12.V9.md` | Task ID: PH12.V9 |
| `T-CZ-05` | qwen-coder | doc-staging | `drafts/dispatch-2026-06-18/T-CZ-05.md` | ```diff |
| `T-EM-01` | deepseek | doc-staging | `drafts/dispatch-2026-06-18/T-EM-01.md` | **Data Broker Removal Partner Program Evaluation** |
| `T-EM-02` | deepseek | doc-staging | `drafts/dispatch-2026-06-18/T-EM-02.md` | Vendor Evaluation: Dark Web Monitoring for MSP Cha |
| `T-EM-04` | deepseek | doc-staging | `drafts/dispatch-2026-06-18/T-EM-04.md` | Exposure Management Tier Inclusion and Pricing Mod |
| `T-EM-05` | deepseek | doc-staging | `drafts/dispatch-2026-06-18/T-EM-05.md` | Exposure Management Compliance Framing   |
| `T-EM-06` | deepseek | doc-staging | `drafts/dispatch-2026-06-18/T-EM-06.md` | Offensive Security Operator's OPSEC Playbook: Miti |
| `T-EM-09` | deepseek | doc-staging | `drafts/dispatch-2026-06-18/T-EM-09.md` | **Service Offering Documentation**   |
| `T-INF-02` | qwen-coder | doc-staging | `drafts/dispatch-2026-06-18/T-INF-02.md` | To resolve the issue where `/healthz` endpoint ret |
| `T-INF-04` | qwen-coder | doc-staging | `drafts/dispatch-2026-06-18/T-INF-04.md` | diff --git a/src/triage_en/prompt.py b/src/triage_ |
| `T-INF-08` | qwen-coder | doc-staging | `drafts/dispatch-2026-06-18/T-INF-08.md` | To address the issue of synchronizing `LOKI_INTERN |
| `T-PL-08` | deepseek | doc-staging | `drafts/dispatch-2026-06-18/T-PL-08.md` | Case Study: Founder Under Attack (Anonymized) |
| `T14.27` | qwen-72b | doc-staging | `drafts/dispatch-2026-06-18/T14.27.md` | Implementation Specification for AI KB Writer |
| `T14.28` | deepseek | doc-staging | `drafts/dispatch-2026-06-18/T14.28.md` | Knowledge Base Articles Seed for Category Cards |
| `T14.39` | claude-sonnet | doc-staging | `drafts/dispatch-2026-06-18/T14.39.md` | T14.39 — Fix Hetzner Default vhost Rebrand Leak |
| `T14.47` | claude-sonnet | doc-staging | `drafts/dispatch-2026-06-18/T14.47.md` | T14.47 — CSP Report-Only on klaravex.com |
| `T14.7
qa
low
Higgsfield
image
ou` |  | doc-staging | `drafts/dispatch-2026-06-18/T14.7
qa
low
Higgsfield
image
ou.md` | T14.7: Image Quality Assessment Report   |
| `T14.7` | claude-sonnet | doc-staging | `drafts/dispatch-2026-06-18/T14.7.md` | T14.7 — Higgsfield Image Output Quality Assessment |

## Post-review correction (2026-06-18 21:20)

Of the 6 `commit-target` bucket items, **4 were hallucinated** — qwen-coder
invented file paths that don't exist in this repo (Spring HealthController,
Python triage_en module, K8s deployment.yaml, WP theme header.php). Moved
to `_quarantine/` to prevent accidental application.

Valid commit-target artifacts (staged as runbooks for manual SSH/WP-CLI execution):
- `runbooks/hetzner/T14.39-nginx-default-vhost-444.md` — needs SSH `hetzner`
- `runbooks/klaravex-com/T14.47-csp-report-only.md` — needs WP-CLI / SFTP on Cloud86

Re-dispatch recommendation for the 4 quarantined items: include actual file
contents in the prompt (read infra/main.py, the docker-compose.yml, etc. into
context first), so the model produces grounded edits instead of inventing.
