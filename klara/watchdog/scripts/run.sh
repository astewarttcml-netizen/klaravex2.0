#!/bin/bash
# Wrapper for /opt/klaravex-watchdog/watchdog.py on Hetzner.
# Loads env from /opt/klaravex-watchdog/env (mode 600), redirects logs.
set -a
. /opt/klaravex-watchdog/env
set +a
exec /usr/bin/python3 /opt/klaravex-watchdog/watchdog.py >> /var/log/klaravex-watchdog.log 2>&1
