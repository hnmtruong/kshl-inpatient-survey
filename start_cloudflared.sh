#!/bin/sh
set -eu
BASE=/home/root_admin/kshl-inpatient-survey
mkdir -p "$BASE/data"
nohup "$BASE/bin/cloudflared" tunnel --protocol http2 --url https://127.0.0.1:8765 --no-tls-verify > "$BASE/data/cloudflared-server.log" 2>&1 < /dev/null &
