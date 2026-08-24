#!/bin/bash
# Wrapper for /opt/klaravex-watchdog/system_health.py on Hetzner.
# Runs every 4h via cron. See README.md.
set -a
. /opt/klaravex-watchdog/env
set +a
exec /usr/bin/python3 /opt/klaravex-watchdog/system_health.py >> /var/log/klaravex-system-health.log 2>&1
