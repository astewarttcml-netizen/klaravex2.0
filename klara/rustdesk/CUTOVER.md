# RustDesk cutover status (2026-08-25)

## Ownership

| Piece | Owner | Notes |
|---|---|---|
| Controller code | **Klaravex2.0** `klara/rustdesk/` | Ported 1:1 (recording, session, protocol, killswitch, consent, …) |
| Relay (`hbbs`/`hbbr`) | **Monolith** docker (`rustdesk-hbbs`, `rustdesk-hbbr`) | Infra relay — stays in live `klaravex` compose; do not duplicate |

## Why relay stays in monolith

Relay is shared network infra (ports, public IDs, NAT traversal), not an app cutover. Moving it would renumber clients and break live sessions. Controller code can run against the existing relay without ownership transfer of the containers.

## Verify

```bash
docker ps --format '{{.Names}} {{.Status}}' | grep rustdesk
ls /home/anthony/Klaravex2.0/klara/rustdesk/{recording,session,protocol}.py
```

## Not done (optional later)

- Point any systemd/operator tray launchers at `Klaravex2.0/klara/rustdesk` if still invoking monolith `infra/rustdesk_controller`.
