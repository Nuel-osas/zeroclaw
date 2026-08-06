#!/usr/bin/env bash
# Guardian — one-command live demo (the thing you film).
#
#   bash demo.sh
#
# Starts the ZeroClaw daemon, pairs the robot gate, launches the Reachy sidecar,
# and arms a threshold so the next scheduled poll fires a real alert.
# Then: the robot turns to you, speaks, and waits for your y/n. Approve and the
# action link lands in Telegram. Deny and nothing is sent.
#
# Env (edit or export before running):
#   DEEPSEEK_API_KEY      model key
#   TG_BOT_TOKEN          telegram bot token
#   GUARDIAN_ROOT         zeroclaw config dir (default: ~/.zeroclaw-guardian)
set -uo pipefail

BIN=$(command -v zeroclaw || echo /opt/homebrew/bin/zeroclaw)
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="${GUARDIAN_ROOT:-$HOME/.zeroclaw-guardian}"
: "${DEEPSEEK_API_KEY:?export DEEPSEEK_API_KEY first}"
: "${TG_BOT_TOKEN:?export TG_BOT_TOKEN first}"
export ZEROCLAW_providers__models__deepseek__main__api_key="$DEEPSEEK_API_KEY"
export ZEROCLAW_channels__telegram__default__bot_token="$TG_BOT_TOKEN"

GW=http://127.0.0.1:42617
DB="$ROOT/data/memory/brain.db"
RUNS="$ROOT/data/sop/runs.db"

cleanup() { echo; echo "▸ stopping…"; kill ${DPID:-0} ${SPID:-0} 2>/dev/null; }
trap cleanup EXIT

echo "▸ config root: $ROOT"
[ -f "$ROOT/config.toml" ] || { echo "  !! no config there. Run setup first (see README)."; exit 1; }

# 1 ── arm the trigger: floor 5% ABOVE the live price so the next poll crosses
python3 - "$DB" <<'PY'
import json, sqlite3, sys, urllib.request, uuid
db = sys.argv[1]
con = sqlite3.connect(db)
row = con.execute("SELECT content FROM memories WHERE key='watch_target'").fetchone()
if not row:
    print("  !! no watch_target in memory — provision the watch first"); sys.exit(1)
mint = row[0]
req = urllib.request.Request(f"https://lite-api.jup.ag/price/v3?ids={mint}",
                             headers={"User-Agent": "guardian/0.1"})
px = json.load(urllib.request.urlopen(req, timeout=20))[mint]["usdPrice"]
floor = f"{px * 1.05:.12f}"
cols = [c[1] for c in con.execute("PRAGMA table_info(memories)")]
templ = dict(zip(cols, con.execute("SELECT * FROM memories WHERE key='watch_target'").fetchone()))
for k, v in (("watch_floor", floor), ("last_alert_at", "never")):
    con.execute("DELETE FROM memories WHERE key=?", (k,))
    r = dict(templ); r["id"] = str(uuid.uuid4()); r["key"] = k; r["content"] = v
    con.execute(f"INSERT INTO memories ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",
                [r[c] for c in cols])
con.commit()
print(f"  armed: price {px:.10f} < floor {float(floor):.10f}  → next poll alerts")
PY

# 2 ── clear old runs so the gate is fresh
python3 - "$RUNS" <<'PY' 2>/dev/null
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
c.execute("DELETE FROM sop_runs"); c.execute("DELETE FROM sop_claims"); c.commit()
print("  cleared previous runs")
PY

# 3 ── daemon
echo "▸ starting daemon…"
"$BIN" --config-dir "$ROOT" daemon > "$ROOT/daemon.log" 2>&1 &
DPID=$!
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do grep -qi "listening for messages" "$ROOT/daemon.log" 2>/dev/null && break; sleep 2; done
grep -qi "listening for messages" "$ROOT/daemon.log" || { echo "  !! daemon failed:"; tail -5 "$ROOT/daemon.log"; exit 1; }

# 4 ── the PHYSICAL GATE (holds the action link; the agent never sees it)
LINK="${ACTION_LINK:-https://jup.ag/swap/BONK-USDC}"
python3 "$HERE/reachy/gate_service.py" --link "$LINK" --timeout 120 &
SPID=$!
sleep 2

cat <<'EOS'

────────────────────────────────────────────────────────────
  ROLLING. Within ~60s the scheduled poll crosses the floor.

   1. the agent crosses the floor and ASKS the gate (nothing sent yet)
   2. Reachy turns to you and asks out loud
   3. press  y  = approve   ·   n  = deny   ·  silence = deny
   4. only on approve is the link released -> it lands in your Telegram
────────────────────────────────────────────────────────────
EOS
wait $SPID
