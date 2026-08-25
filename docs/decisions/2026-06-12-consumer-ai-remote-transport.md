# Decision: Consumer AI remote-session transport (2026-06-12)

**Status:** DECIDED — fork RustDesk self-hosted as the consumer §1+§2 transport. Build §3 controller fresh against the RustDesk protocol. Reject agent-RDP for consumer scope (managed-Windows only). Reject from-scratch §1+§2.
**Scope:** CONSUMER ONLY — $79 one-off support session, no pre-deployed agent. B2B managed-endpoint flow is covered by `2026-06-12-b2b-ai-transport-path.md` (Robin / Atera).
**Owner:** Anthony · **Author:** Loki (G32 deliverable) · **Related:** `docs/architecture/ai-remote-session.md`, `infra/rustdesk-server-DEPLOYED.md`

## Question

The original ai-remote-session.md spec (G28) decided to build §1 customer-side helper binary (screen capture + input injection, Win/macOS, code-signed, kill-switch) and §2 WebSocket relay from scratch on the existing Hetzner CX22. §3 AI controller is Loki/Opus and is unaffected by this decision.

Anthony asked: instead of building §1+§2 from scratch, **fork RustDesk self-hosted**? RustDesk already provides:
- Cross-platform helper client (Win/macOS/Linux),
- Screen capture and input injection,
- NAT traversal + relay/ID server hostable on the same Hetzner box,
- One-click session code/ID,
- Pro Web Console + REST API.

That maps almost 1:1 onto §1 (helper) + §2 (relay) and removes the two hardest from-scratch problems (NAT traversal, reliable cross-OS input injection).

A second transport was also raised — **agent-RDP** (`github.com/thisnick/agent-rdp`) — for managed Windows where RDP + Windows UI Automation gives a semantic element tree over a Dynamic Virtual Channel, far more reliable and cheaper than pixel-guessing. The question: should the consumer flow ALSO use agent-RDP?

## Constraints + facts

- Consumer flow has **no pre-installed agent**. The customer is on the phone with Klara, has just paid $79, and is being walked through downloading + launching a helper. Anything that requires "ask IT to deploy this MSI to your fleet" is out.
- RustDesk relay (`hbbs` + `hbbr`) is **LIVE on the Hetzner public edge** at `178.105.84.32`, server key `D7BrbrWQDesAj1zLf18Vj+JUYKgwsAmH5iW2zNd0ScI=`. See `infra/rustdesk-server-DEPLOYED.md`. §2 of the spec is therefore *already supplied by RustDesk* on production infrastructure.
- Customer entry point `https://support.klaravex.com` is LIVE, ships pre-configured Windows helpers (relay + key baked into the filename → zero-config) and Mac DMGs. The §1 surface a customer touches today is the RustDesk helper.
- RustDesk is licensed **AGPL-3.0** (server: hbbs/hbbr; client: rustdesk). Commercial / hosted-SaaS use without source disclosure is restricted. The license is the central decision input.
- Apple notarization + a Sectigo EV Code Signing certificate for Windows are required regardless of which §1 path is chosen — see "Code-signing burden" below.

## Options

### Option 1 — Fork RustDesk self-hosted for §1 + §2 (RECOMMENDED)

- §2 relay: already live on Hetzner. No further build.
- §1 helper: fork rustdesk/rustdesk, strip the unused features (file transfer manager UI, system tray persistence, remote print, audio), brand the UI, bake in `support.klaravex.com` as the fixed relay + server key. Ship signed Windows binary + notarized macOS DMG via `support.klaravex.com/download/<session-token>`.
- §3 AI controller: Loki connects to the same RustDesk session AS A CLIENT (using rustdesk's client protocol library or `librustdesk`), receives the framebuffer, sends mouse + keyboard events. This is the new build — narrow scope, no NAT/transport/cross-OS-input work, just "Opus vision → action prediction → emit RustDesk input events → confirm via Klara → repeat."

**License + IP plan (AGPL-3.0):** RustDesk's AGPL applies to the modified RustDesk binaries. Klaravex's strategy:
- Treat the forked RustDesk client + the hbbs/hbbr relay as **AGPL-licensed components that we distribute and host**. We comply by publishing our fork's source (e.g. `github.com/klaravex/klaravex-helper`) and noting it in the "About" screen of the helper. This is the same pattern that other commercial deployments of RustDesk (e.g. RustDesk's own paid hosted product) use.
- Keep Loki's controller (§3 AI brain), the support.klaravex.com web app, the session-token issuance service, billing integration, and the dataset capture pipeline (§5) in **separate repositories** that *use* the RustDesk client via its network protocol — NOT by linking AGPL code into proprietary code. As long as the interaction is over the documented network protocol, the AGPL does not propagate to the controller side. (This is the standard "AGPL bright line" — process-boundary + network-protocol interaction does not trigger combined-work.)
- IP moat survives: the moat is the AI controller, the audit/consent infrastructure, the voice integration, the dataset, the brand. None of that is in the forked RustDesk binary.
- **Mitigations to confirm:** US tech attorney sign-off that the protocol-boundary separation holds (cheap — ~$500 one-time review). If counsel disagrees, fall back to running stock unmodified RustDesk binaries with only the build-time defaults patched (relay address, server key, application name) — this trims the modification surface to a level that's safely "configuration, not derivative work" under most readings.

**Code-signing burden:** Same as from-scratch. Sectigo EV Code Signing (~$300-400/yr, ~3-5 day issuance, instant SmartScreen reputation) for Windows. Apple Developer Program ($99/yr) + notarization for macOS. **Forking does NOT inherit RustDesk's signed binaries** — once we modify, we must re-sign with Klaravex's own certificates. The cert + notarization cost is the same in all build options; this is a wash.

**Operational fit on existing CX22:** Excellent. Relay is already live there. CX22 (2 vCPU, 4 GB) handles 10-20 concurrent RustDesk sessions per prior benchmark in the architecture spec; consumer flow projection is <5 concurrent. No infrastructure change needed.

**Manual-fallback collapse (G31):** RustDesk self-hosted ALSO solves the manual-fallback case (Anthony connects to the customer's same session via the same relay). The fallback tool and the core AI transport collapse into one stack — fewer moving parts, lower training-data drift, lower vendor surface. Net positive vs. running RustDesk-for-AI + AnyDesk-for-fallback.

### Option 2 — Build §1 + §2 from scratch (REJECTED)

- §1: implement screen capture + input injection on Windows (DXGI Desktop Duplication + SendInput, or a kernel driver for UAC) and macOS (CGWindowList + CGEvent + Accessibility API). Code-sign and notarize. Cross-platform installer.
- §2: implement WebSocket relay (~1 week), NAT traversal heuristics (~2-4 weeks of trial-and-error), TLS, signed-token auth, frame ferrying, action channel.
- Total estimated effort: **8-16 weeks** of focused engineering before first paid customer, with ongoing maintenance.

**Why rejected:** the relay is already live in Option 1, and the input-injection work is the part that historically blocks remote-control projects for months. Forking a battle-tested AGPL client buys ~3 months of velocity at the cost of one source-disclosure obligation. The trade is one-sided.

There is no scenario where from-scratch beats fork-RustDesk on time-to-launch, and the IP moat lives in §3 (controller) not §1+§2 (transport), so the build-it-from-scratch IP argument doesn't apply.

### Option 3 — agent-RDP as a SECOND consumer transport (REJECTED for consumer; KEPT as B2B managed-Windows option)

- agent-RDP (github.com/thisnick/agent-rdp) gives a semantic UI Automation element tree over an RDP Dynamic Virtual Channel — far more reliable than pixel-guessing.
- **Why rejected for CONSUMER:** RDP is a managed-endpoint paradigm. Enabling RDP on a consumer Windows machine requires admin elevation, Home edition (a huge slice of consumers) does NOT allow incoming RDP, and macOS does not host RDP. The DVC also needs a pre-deployed agent — the same blocker that disqualifies Atera Robin for consumer.
- **KEPT for B2B managed-Windows / unattended scope:** where agents are pre-deployed and admin controls are owned by Klaravex, agent-RDP is the higher-fidelity alternative to vision-on-pixels. Defer that decision to a future doc *after* Robin's autonomy ceiling is measured in production — if Robin closes 70-80% autonomously, the marginal value of agent-RDP for the remaining 20-30% may not justify the engineering cost.

### Option 4 — Hosted SaaS RustDesk (RustDesk Pro Server) (REJECTED)

- Pay RustDesk's hosted Pro tier and skip self-hosting.
- **Why rejected:** Klaravex's positioning ("self-hosted, on our own EU/US infrastructure, customer data never leaves our edge") is a sales asset. Routing customer screen frames through a third-party SaaS undermines that. Cost is also worse at scale (~$10-30/mo per concurrent connection vs. Hetzner CX22 amortized).

## Recommendation

**Adopt Option 1 — fork RustDesk self-hosted for §1 + §2. §3 AI controller is built fresh against the RustDesk protocol as G34. agent-RDP is parked for a future B2B managed-Windows decision and NOT in consumer scope.**

Order of operations:
1. (DONE) RustDesk relay live on Hetzner — `infra/rustdesk-server-DEPLOYED.md`.
2. (DONE) `support.klaravex.com` ships pre-configured Windows helper + Mac DMG — zero-config from filename-embedded relay + key.
3. (NEXT — G34) Build the headless RustDesk client controller: framebuffer ingest → Opus vision prediction → confirmation gate → mouse/keyboard injection → loop.
4. (PARALLEL) Loki integrates the four Klara tools (`start_rustdesk_session`, `next_screen_action`, `confirm_action`, `end_rustdesk_session`) per ai-remote-session.md §4.
5. (PARALLEL) US tech attorney reviews AGPL separation strategy — confirm protocol-boundary mitigation OR fall back to unmodified upstream binaries.
6. (BEFORE FIRST PAID CUSTOMER) Sectigo EV code-signing cert procured (~3-5 day issuance) + Apple notarization wired into the build.

## Consent + visible AI-control + recording + kill-switch (carries into the chosen transport)

The forked helper MUST surface these regardless of RustDesk's defaults — these are spec-required (ai-remote-session.md §1 and §6) and the forked client UI is exactly where they go:

- **Pre-session consent modal** with checkbox + explicit text including session_id and "I authorize Klaravex AI to view and control this computer for the duration of this session." Recorded to immutable log (S3 + SHA-256 hash chain + daily OpenTimestamps anchor).
- **Always-visible "AI is controlling your computer" indicator** — pinned banner in the helper UI; cannot be hidden. Distinct from RustDesk's default connection indicator. Visually loud enough that an observer (e.g. customer's family member walking in) understands the state.
- **Three-path kill-switch** — system-tray STOP button + global hotkey `Ctrl+Shift+X` (`Cmd+Shift+X` on macOS) + server-side override that the relay enforces within 1 second.
- **Session recording**: helper streams to relay; relay tee's to S3 for the 90-day retention window. Customer is told this before consent.
- **Self-uninstall on session end** — opt-in persistence is disabled in v1.

These are §1 work items in G34 and are not negotiable.

## Acceptance criteria (this doc satisfies G32)

- [x] Decision doc in `docs/decisions/` recommends **fork RustDesk** for §1+§2 with rationale.
- [x] AGPL/licensing implications for commercial MSP use explicitly addressed, with separation strategy and counsel-review fallback.
- [x] agent-RDP evaluated; rejected for consumer scope, parked for managed-Windows/B2B decision.
- [x] Code-signing burden under each option stated: forking does NOT inherit RustDesk's signed binaries; Sectigo EV + Apple notarization required either way.
- [x] Consent + visible AI-control indicator + session recording + kill-switch requirements explicitly carried into the chosen transport (the forked helper).
- [x] `docs/architecture/ai-remote-session.md` §1 and §2 STATUS lines to be updated in the companion change to mark the transport decision as DECIDED via RustDesk fork.

## Open items

- US tech attorney AGPL-separation review (~$500, ~1 week).
- Sectigo EV Code Signing procurement (3-5 day issuance).
- Apple notarization wired into build pipeline.
- 10-session concurrent RustDesk load test on CX22 to confirm the 10-20 ceiling number before first paid customer.
