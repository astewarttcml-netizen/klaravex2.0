# Azure Support Ticket — klaravex-db wedge (2026-08-13)

**Status:** READY TO FILE · **Owner:** Anthony MUST file (host RBAC cannot)
**Server:** `klaravex-db` · RG `klaravex-prod` · Sub `4cccf368-61d5-42f7-b1d7-59e798b1be24`
**FQDN:** `klaravex-db-r2.postgres.database.azure.com` (hosts 20.12.219.241)

> **Filing info (verified 2026-08-13):**
> - Service (`problemClassifications` service id): `191ddd48-d790-61f4-315b-f621cdd66a91` — Azure Database for PostgreSQL flexible server
> - **Problem classification:** `1104ac54-00a0-982b-8e6c-770bbb59f8b4` — Create, Restart, Scale and Drop Resources / **Scaling across compute tier** (matches the B2s scale that Failed at 08:08:30Z). Alternative: `d15f659e-3a10-d2a3-3b4b-08c6923dcaa1` — Start/stop server.
> - **RBAC:** this session's principal (`3f3c2c02-...`) is `AuthorizationFailed` for `Microsoft.Support/supportTickets/action` at sub + tenant scope. File from an Owner identity (Portal, or CLI `az support in-subscription tickets create`), or grant `Microsoft.Support/supportTickets/action`. Severity **critical** (production DB down, queue-blocking).
> - Contact block requires: first/last name, email, country (likely `USA`), language (likely `en-us`), timezone (likely `Eastern Standard Time`), contact method, advanced diagnostic consent.

## Problem statement

`klaravex-db` (Azure Database for PostgreSQL Flexible Server, **Standard_B2s**,
PG 15, single-server, zone 2) is stuck in `state=Updating` and is **unreachable**
(read-only `psql` to port 5432 times out) since **2026-08-13T08:08Z**. It has not
recovered after **2.5+ hours**. Every control-plane write is accepted into the
operation queue but **fails at apply time**; the state machine never leaves
`Updating`. The server is unprovisionable and down.

## Timeline (UTC 2026-08-13)

| Time | Operation | Result |
|---|---|---|
| 08:08:30Z | `az postgres flexible-server update --sku-name Standard_B2s` (scale B1ms→B2s) | Activity log `flexibleServers/write` **Failed** |
| 08:09:30Z | ip-watchdog `firewallRules/write` | **Failed** (`ServerIsBusy`) |
| 08:09-10:00Z | continuous | `state=Updating`, DB unreachable, only `flexibleServers/read` health polls |
| ~09:xxZ | re-issue SKU update | `ServerIsBusy: Cannot complete operation while server 'klaravex-db' is busy processing another operation` |
| ~09:55Z | `az postgres flexible-server restart` | **ServerIsNotReady** (restart/stop only on Ready) |
| 10:02:23Z | idempotent REST PATCH of *exact current* config (api-version 2024-08-01) | `UpsertServerManagementOperationV2` **Started** → activity log **Failed**; state unchanged |
| 10:25:02Z | REST POST `stop` | `StopServerManagementOperation` accepted, no state change |
| 10:27:39Z | REST POST `start` | `StartServerManagementOperation` accepted, no state change |

## What we tried (API — exhausted)

1. **Restart** → `ServerIsNotReady` (gated on Ready).
2. **Re-scale** → `ServerIsBusy` (phantom in-flight op).
3. **Idempotent REST PATCH** exact current config → accepted but **Failed at apply**.
4. **REST stop** → accepted, no state change.
5. **REST start** → accepted, no state change.

Diagnosis: control plane accepts writes into an operation queue, but every op
**fails at apply** and `state` never leaves `Updating`. This is not a resumable
scale; the server provisioning state machine is wedged and requires Microsoft-side
intervention.

## Requested action

Please investigate and clear the stuck `Updating` state on `klaravex-db`, or
restore the server to `Ready`/redundant provisioning. The B2s scale was a valid
no-op resubmission of the current desired SKU. If the state machine is corrupted,
please reset it to `Ready` (or `Stopped` for an explicit Stop/Start cycle).

## Impact

Production Klaravex backend DB is fully down. All stateful workflows, the
`klaravex.note_submissions` memory pipeline (currently falling back to local
JSONL), and any read/write against the domain DB are blocked until `Ready`.

## Contact / reference

- Subscription: `4cccf368-61d5-42f7-b1d7-59e798b1be24`
- Resource group: `klaravex-prod`
- Server: `klaravex-db`
- First failed operation ID: `flexibleServers/write` @ 08:08:30Z (Started 08:08:30 / Failed)
