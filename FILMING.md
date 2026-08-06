# Filming the demo (≤3 min, no slides)

## Terminal A — the physical gate (holds the link)
```bash
cd ~/Downloads/runs/zeroclaw-bounty/guardian
python3 reachy/gate_service.py --link "https://jup.ag/swap/BONK-USDC" --timeout 120
```
Leave it running. This window is where you press **y**.

## Terminal B — the agent
```bash
cd ~/Downloads/runs/zeroclaw-bounty/guardian
export DEEPSEEK_API_KEY="<your key>"
export TG_BOT_TOKEN="<your bot token>"
bash demo.sh
```
It arms the threshold and starts the daemon; the scheduled poll fires within ~60s.

## Shot list
1. **Open on the robot** sitting idle. Phone (Telegram) beside it. 5s.
2. **Terminal B**: the poll runs, price is below the floor. Say: *"it crossed."*
3. **The robot turns to you and asks out loud.** Let it speak — this is the hero beat.
4. **Press `y` in Terminal A** on camera. (Or `n` first to show it fail closed — strong.)
5. **Phone**: the alert + link arrives. Tap it — the wallet opens to sign. 
6. Close on: *"The agent never had that link. Only the robot could release it."*

## If you have 30 extra seconds — the money shot
Run it once and press **n** (or say nothing). The robot droops, and Telegram shows
only *"Alert stood down at the robot."* No link. Then run again and press **y**.
Deny-then-approve in one video proves the gate is real.
