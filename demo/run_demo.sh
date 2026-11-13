#!/usr/bin/env bash
# No-hardware demo (decision X31): runs the logger on vcan0 against the session 142
# scenario and verifies the hash chain. Also the CI end-to-end smoke test.
#
#   bash demo/run_demo.sh            (Linux machine or VM with can-utils)
#
# Steps: bring up vcan0 if needed; start the logger listen-only with the example
# config and inventory in a temporary folder; replay the session 142 raw capture,
# in which a scan tool claims address 249; stop the logger (clean session end);
# verify the chain; check that a connection_start was written for the scan tool.
# The laptop tool joins the demo in build step 7.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
IFACE="${IFACE:-vcan0}"
PYTHON="${PYTHON:-python3}"
WORK="$(mktemp -d)"
export PYTHONPATH="$REPO/src${PYTHONPATH:+:$PYTHONPATH}"

echo "== 1. Virtual CAN interface $IFACE"
if ! ip link show "$IFACE" >/dev/null 2>&1; then
  sudo modprobe vcan
  sudo ip link add dev "$IFACE" type vcan
  sudo ip link set up "$IFACE"
fi
command -v canplayer >/dev/null || { echo "canplayer not found: install can-utils"; exit 2; }

echo "== 2. Start the logger (listen-only), files in $WORK"
"$PYTHON" -m j1939logger.main \
  --config "$REPO/docs/examples/cfg-v3.json" \
  --inventory "$REPO/docs/examples/inv-v2.json" \
  --interface "$IFACE" --root "$WORK" >"$WORK/logger.out" 2>&1 &
LOGGER=$!
trap 'kill "$LOGGER" 2>/dev/null || true' EXIT
for _ in $(seq 100); do
  if compgen -G "$WORK/card/sessions/*.jsonl" >/dev/null; then break; fi
  sleep 0.1
done
compgen -G "$WORK/card/sessions/*.jsonl" >/dev/null || { cat "$WORK/logger.out"; echo "logger did not start"; exit 1; }

echo "== 3. Replay the session 142 capture (a scan tool claims SA 249)"
canplayer -t -g 2 -I "$REPO/docs/examples/s000142_c2_e1.log" "$IFACE=can0"
sleep 1

echo "== 4. Stop the logger (clean session end)"
kill -TERM "$LOGGER"
wait "$LOGGER" || true
trap - EXIT

echo "== 5. Verify the chain"
"$PYTHON" "$REPO/tools/verify_chain.py" "$WORK/card/sessions"

echo "== 6. Records written"
"$PYTHON" - "$WORK/card/sessions" <<'EOF'
import json, sys
from pathlib import Path
records = []
for f in sorted(Path(sys.argv[1]).glob("*.jsonl")):
    records += [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines()]
for r in records:
    extra = f" sa={r['sa']} category={r['category']}" if r["type"] == "connection_start" else ""
    print(f"  rec {r['rec']:>3}  {r['type']:<18} {r['sev']:<6}{extra}")
starts = [r for r in records if r["type"] == "connection_start" and r.get("sa") == 249]
if not starts:
    sys.exit("FAIL: no connection_start for the scan tool at SA 249")
print("demo passed: the scan tool's claim gave a chained connection_start")
EOF
