#!/usr/bin/env bash
# Try Guardian end-to-end on your own machine — no Telegram, no robot required.
# The robot's job (approve/deny at the gate) falls back to your keyboard, which is
# still "physical presence at the machine" — the whole point.
#
# Usage:
#   export DEEPSEEK_API_KEY=sk-...        # your DeepSeek key
#   bash try_guardian.sh
#
# What happens: a throwaway ZeroClaw instance watches SOL price with an
# intentionally-high floor (so it always alerts), the daemon's scheduler fires the
# poll every minute, the alert parks at the gate, and YOU approve or deny at the
# keyboard. Approve -> the action link is "delivered". Deny/timeout -> nothing.
set -euo pipefail

BIN=$(command -v zeroclaw || echo /opt/homebrew/bin/zeroclaw)
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${GUARDIAN_TEST_ROOT:-$HOME/.zeroclaw-guardian-try}"
: "${DEEPSEEK_API_KEY:?set DEEPSEEK_API_KEY first (export DEEPSEEK_API_KEY=sk-...)}"
export ZEROCLAW_providers__models__deepseek__main__api_key="$DEEPSEEK_API_KEY"

echo "▸ fresh instance at $ROOT"
rm -rf "$ROOT"; mkdir -p "$ROOT/workspace/sops"
"$BIN" --config-dir "$ROOT" skills bundle add guardian >/dev/null
"$BIN" --config-dir "$ROOT" skills install "$HERE/skills/guardian" --bundle guardian >/dev/null
cp -r "$HERE/sops/alert-gate" "$ROOT/workspace/sops/"

cat > "$ROOT/config.toml" <<EOF
schema_version = 3
[providers.models.deepseek.main]
model = "deepseek-v4-flash"
[risk_profiles.default]
level = "supervised"
auto_approve = ["http_request","memory_recall","memory_store","sop_execute"]
[agents.guardian]
model_provider = "deepseek.main"
risk_profile   = "default"
skill_bundles  = ["guardian"]
cron_jobs      = ["poll_position"]
system_prompt  = "You are Guardian. Follow the guardian skill exactly. You hold no keys. Alerts only via the alert-gate SOP. Silence when the position is fine."
[http_request]
enabled = true
allowed_domains = ["lite-api.jup.ag","api.mainnet-beta.solana.com","solana-rpc.publicnode.com"]
[skill_bundles.guardian]
[sop]
enabled = true
persist_runs = true
approval_timeout_secs = 300
sops_dir = "$ROOT/workspace/sops"
[sop.approval.groups.robot]
members = ["http:robot-gate"]
[sop.approval.policies.robot]
required_group = "robot"
quorum = 1
[cron.poll_position]
name = "Poll position health"
job_type = "agent"
prompt = "Run the guardian skill poll procedure once; output nothing if fine."
schedule = { kind = "cron", expr = "* * * * *" }
enabled = true
uses_memory = true
allowed_tools = ["http_request","memory_recall","memory_store","sop_execute"]
session_target = "isolated"
[cron.poll_position.delivery]
mode = "none"
[memory]
backend = "sqlite.default"
auto_save = true
[storage.sqlite.default]
[secrets]
encrypt = true
EOF

echo "▸ teaching it the watch config (SOL, floor \$500 so it always alerts for the demo)"
"$BIN" --config-dir "$ROOT" agent -a guardian -m \
  "Store as core memory then confirm one line: watch_kind=price, watch_target=So11111111111111111111111111111111111111112, watch_floor=500, action_blink=https://jup.ag/swap/SOL-USDC, last_alert_at=never" >/dev/null

echo "▸ starting daemon…"
"$BIN" --config-dir "$ROOT" daemon > "$ROOT/daemon.log" 2>&1 &
DPID=$!
trap 'kill $DPID 2>/dev/null; echo; echo "▸ stopped."' EXIT
until grep -q "Gateway listening" "$ROOT/daemon.log" 2>/dev/null; do sleep 1; done
CODE=$(grep -oE "X-Pairing-Code: [0-9]+" "$ROOT/daemon.log" | grep -oE "[0-9]+" | head -1)
TOKEN=$(curl -s -X POST http://127.0.0.1:42617/pair -H "X-Pairing-Code: $CODE" | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

echo "▸ daemon up. The scheduler polls every minute; SOL is far below \$500 so an"
echo "  alert will park at the robot gate shortly. This is your robot: press y/n."
echo
python3 "$HERE/reachy/gate_sidecar.py" --token "$TOKEN" --timeout 120
