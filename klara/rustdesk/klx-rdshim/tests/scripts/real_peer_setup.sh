#!/usr/bin/env bash
# real_peer_setup.sh — Spin up a real RustDesk client in a Docker container
# on the Hetzner host so that klx-rdshim can connect to it through the
# production hbbs/hbbr relay.
#
# Usage:
#   real_peer_setup.sh up <container_name>   # start container, return peer_id
#   real_peer_setup.sh xdotool <container_name> <args...>   # run xdotool inside
#   real_peer_setup.sh cursor <container_name>   # report xdotool getmouselocation
#   real_peer_setup.sh tail <container_name>     # tail rd logs
#   real_peer_setup.sh down <container_name>   # tear it down
#   real_peer_setup.sh logs <container_name>   # dump rustdesk service log
#
# Adapted from .private/scan-results/rustdesk-e2e-test.sh (checkpoint 2),
# but simplified to a single customer-side container — the operator side
# is klx-rdshim running from the developer host.

set -euo pipefail

SSH="ssh -F ${HOME}/.ssh/config hetzner"
RELAY_HOST="87.99.147.244"
RELAY_KEY="E2+699SkYhlEsyjaizRhI+2kuvxxGheisWarfJHbkVA="
IMAGE_TAG="rustdesk-test-client:local"
NET="rustdesk-test-net"

cmd="${1:?cmd required}"
name="${2:?name required}"
shift 2

case "$cmd" in
  up)
    # Reuse the existing test image (built by the prior checkpoint 2
    # e2e script). If it doesn't exist, instruct the caller to build it.
    if ! $SSH "docker images $IMAGE_TAG --format '{{.Tag}}' | grep -q local"; then
      echo "ERROR: image $IMAGE_TAG missing. Run .private/scan-results/rustdesk-e2e-test.sh first to build it." >&2
      exit 1
    fi
    # Ensure isolated network exists
    $SSH "docker network create $NET >/dev/null 2>&1 || true"
    $SSH "docker rm -f $name >/dev/null 2>&1 || true"
    $SSH "docker run -d --name $name --network $NET --hostname $name $IMAGE_TAG >/dev/null"

    # Write the relay config BEFORE rustdesk starts so the first launch
    # registers against our hbbs (not the default rs-ny.rustdesk.com).
    CFG="rendezvous_server = \"${RELAY_HOST}:21116\"
nat_type = 1
serial = 0

[options]
custom-rendezvous-server = \"${RELAY_HOST}\"
relay-server = \"${RELAY_HOST}\"
api-server = \"\"
key = \"${RELAY_KEY}\"
direct-server = \"Y\""
    printf '%s\n' "$CFG" | $SSH "docker exec -i $name bash -c 'mkdir -p /root/.config/rustdesk && cat > /root/.config/rustdesk/RustDesk2.toml'"

    # Start Xvfb in background, then rustdesk service + GUI. Use bash -lc
    # so the env is set up properly. We deliberately do NOT use docker
    # exec -d for the service-launch step because that gives the daemon
    # no chance to start before we move on.
    $SSH "docker exec -d $name bash -c 'Xvfb :99 -screen 0 1024x768x24 >/tmp/xvfb.log 2>&1'"
    sleep 2
    $SSH "docker exec -d $name bash -c 'DISPLAY=:99 rustdesk --service >/tmp/rd-svc.log 2>&1'"
    sleep 4
    $SSH "docker exec -d $name bash -c 'DISPLAY=:99 LIBGL_ALWAYS_SOFTWARE=1 rustdesk >/tmp/rd-gui.log 2>&1'"

    # Wait for the hbbs to record this client's pubkey registration; that's
    # the moment we know which numeric peer_id rustdesk assigned to it.
    # Look at hbbs logs for "update_pk <id> [::ffff:172.X.Y.Z]:port:port"
    # entries that match our container's IP.
    sleep 5
    IP=$($SSH "docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' $name")
    if [ -z "$IP" ]; then
      echo "ERROR: could not determine container IP for $name" >&2
      exit 1
    fi
    for try in 1 2 3 4 5; do
      ID_LINE=$($SSH "docker logs rustdesk-hbbs --since 2m 2>&1 | grep -E 'update_pk [0-9]+ \[::ffff:$IP' | tail -1" || true)
      if [ -n "$ID_LINE" ]; then
        break
      fi
      sleep 4
    done
    if [ -z "$ID_LINE" ]; then
      echo "ERROR: no registration seen in hbbs log for $name ($IP)" >&2
      $SSH "docker exec $name bash -c 'cat /tmp/rd-svc.log 2>/dev/null | head -100'" >&2 || true
      exit 2
    fi
    # The hbbs log line is: "[ts] INFO [path] update_pk <id> [::ffff:ip]:port ..."
    # Extract <id> by matching `update_pk N` directly.
    PEER_ID=$(echo "$ID_LINE" | grep -oE 'update_pk [0-9]+' | awk '{print $2}')
    if [ -z "$PEER_ID" ]; then
      echo "ERROR: could not extract peer id from log line: $ID_LINE" >&2
      exit 3
    fi
    echo "$PEER_ID"
    ;;
  xdotool)
    $SSH "docker exec $name bash -c 'DISPLAY=:99 xdotool $*'"
    ;;
  cursor)
    $SSH "docker exec $name bash -c 'DISPLAY=:99 xdotool getmouselocation'"
    ;;
  tail)
    $SSH "docker exec $name bash -c 'tail -50 /tmp/rd-svc.log 2>/dev/null; echo ---gui---; tail -50 /tmp/rd-gui.log 2>/dev/null'"
    ;;
  logs)
    $SSH "docker exec $name bash -c 'cat /tmp/rd-svc.log /tmp/rd-gui.log 2>/dev/null'"
    ;;
  down)
    $SSH "docker rm -f $name >/dev/null 2>&1 || true"
    ;;
  *)
    echo "unknown cmd: $cmd" >&2
    exit 64
    ;;
esac
