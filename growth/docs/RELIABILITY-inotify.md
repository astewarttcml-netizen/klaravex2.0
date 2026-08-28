# Reliability Fix E — `fs.inotify.max_user_instances`

> Status: **RECOMMENDATION ONLY (not applied)** — passwordless sudo was
> unavailable in the executing session, so the kernel sysctl was NOT changed.
> Anthony (or an operator with sudo) must apply the commands below.

## Symptom
`fs.inotify.max_user_instances=128`, with ~109 in use (85%). At this level the
> kernel starts refusing new inotify instances, which degrades systemd's
> cgroup watch paths and slows / breaks clean stop/kill of `growth-api.service`
> (root cause ref `d7b0af26`).

## Current value
```
fs.inotify.max_user_instances = 128   (observed 2026-08-25)
inotify instances in use   = ~109
```

## Recommended value
`512` — comfortably above current usage and leaves headroom for the growth
> stack + uvicorn + claude subprocess watchers.

## Exact commands (requires sudo)
```bash
# 1. Apply immediately (runtime):
sudo sysctl -w fs.inotify.max_user_instances=512

# 2. Persist across reboots:
echo 'fs.inotify.max_user_instances=512' | sudo tee /etc/sysctl.d/99-klaravex-inotify.conf
sudo sysctl --system
```

## Verification
```bash
sysctl fs.inotify.max_user_instances
# expect: fs.inotify.max_user_instances = 512
```

## Rollback
```bash
sudo sysctl -w fs.inotify.max_user_instances=128
sudo rm /etc/sysctl.d/99-klaravex-inotify.conf
sudo sysctl --system
```
