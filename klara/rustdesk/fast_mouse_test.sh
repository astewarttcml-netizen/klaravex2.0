#!/bin/bash
# Fast mouse control test — no vision, just connect and move mouse immediately
# Usage: ./fast_mouse_test.sh <peer_id> <password>
set -eu
PEER_ID="${1:?Usage: $0 <peer_id> <password>}"
PASSWORD="${2:?Usage: $0 <peer_id> <password>}"
SHIM="$(dirname "$0")/klx-rdshim/target/release/klx-rdshim"

KLX_RDSHIM_MODE=real KLX_SKIP_SIGNEDID_VERIFY=1 "$SHIM" <<EOF
{"kind":"connect","customer_id":"$PEER_ID","session_password":"$PASSWORD","relay_host":"87.99.147.244","relay_key":"E2+699SkYhlEsyjaizRhI+2kuvxxGheisWarfJHbkVA=","hbbs_port":21115,"hbbr_port":21117}
{"kind":"event","event_kind":"mouse_move","x":100,"y":100}
{"kind":"event","event_kind":"mouse_move","x":500,"y":500}
{"kind":"event","event_kind":"mouse_move","x":960,"y":600}
{"kind":"event","event_kind":"mouse_click","x":960,"y":600,"button":"left"}
{"kind":"event","event_kind":"mouse_move","x":200,"y":200}
{"kind":"event","event_kind":"mouse_move","x":1500,"y":900}
{"kind":"event","event_kind":"mouse_move","x":960,"y":600}
EOF
