#!/usr/bin/env bash
#
# klaravex-beat-watchdog.sh — detect a stalled Celery beat and force-restart the
# worker so scheduling self-heals after a silent hang.
#
# Why this exists
# ---------------
# klaravex_worker runs Celery with `--beat --pool=solo`, i.e. the scheduler and
# task execution share a single thread. A hung task (e.g. a slow RARV LLM call)
# stalls the scheduler WITHOUT the process ever exiting — so Docker's
# `restart: unless-stopped` policy never fires (it only acts on process exit)
# and the container's healthcheck (a `celery inspect ping`) can still succeed
# against the still-alive-but-stuck worker. That is a *silent hang*, not a
# crash, and it is exactly the failure this watchdog exists to catch.
#
# Mechanism
# ---------
# Celery beat rewrites /tmp/celerybeat-schedule inside the container every time
# it dispatches (or scans) an entry. Its mtime is therefore a faithful heartbeat
# of the scheduler. We read that mtime via `docker exec stat` and persist it on
# the host (which survives the container restart that /tmp does not). On each
# run we compare the current mtime against the persisted stamp; if it has not
# advanced beyond STALL_SECONDS, beat is wedged and we `docker restart` the
# worker. `unless-stopped` then brings the container back on the host's own
# restart-free path.
#
# Invoked by klaravex-beat-watchdog.timer (every 2 min). No args, no env.
#
set -u

CONTAINER="klaravex_worker"
SCHEDULE_PATH="/tmp/celerybeat-schedule"
STATE_FILE="/var/lib/klaravex/beat-watchdog.state"
LOG_TAG="klaravex-beat-watchdog"

# Beat dispatches at least every 2 minutes (min cron entry is every 1 min;
# the RARV heartbeat is every 30 min but the mailbox poll is every 2 min).
# Two full timer intervals + grace = anything over 4 min without an mtime
# advance is a stall.
STALL_SECONDS=240

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# --- Resolve current schedule mtime (epoch seconds) -------------------------
if ! mtime=$(docker exec "$CONTAINER" stat -c '%Y' "$SCHEDULE_PATH" 2>/dev/null); then
    # Container not running (crashed, not yet up after a prior restart, or
    # docker daemon hiccup). Don't spam-restart; `unless-stopped`/healthcheck
    # own that path. Record state and exit clean.
    log "container '$CONTAINER' exec failed (not running?) — deferring to restart policy"
    exit 0
fi

case "$mtime" in
    ''|*[!0-9]*) log "unexpected mtime '$mtime' — ignoring"; exit 0 ;;
esac

# --- Compare against persisted stamp ----------------------------------------
mkdir -p "$(dirname "$STATE_FILE")"
now=$(date +%s)

if [ -f "$STATE_FILE" ]; then
    prev=$(cat "$STATE_FILE" 2>/dev/null | tr -dc '0-9')
    if [ -n "$prev" ] && [ "$prev" -le "$mtime" ]; then
        stalled=$(( now - mtime ))
        if [ "$stalled" -ge "$STALL_SECONDS" ]; then
            log "STALL: schedule mtime advanced $(( mtime - prev ))s but last tick ${stalled}s ago (>= ${STALL_SECONDS}s) — restarting $CONTAINER"
            if docker restart "$CONTAINER" >/dev/null 2>&1; then
                log "restart issued for $CONTAINER"
                # Clear stamp so next run re-baselines against the fresh schedule file.
                rm -f "$STATE_FILE"
            else
                log "restart of $CONTAINER FAILED — leaving stamp intact"
            fi
        else
            # Advancing and fresh — healthy.
            :
        fi
    fi
fi

# Persist today's mtime for the next watchdog pass.
echo "$mtime" > "$STATE_FILE"
exit 0
