# Guardian — a DeFi watchdog whose approval gate is a robot in your room

A ZeroClaw agent watches **one position you actually care about** on Solana and
stays silent until it needs you. When a threshold crosses, a **Reachy Mini turns
to you and asks out loud**. Only a person physically present can approve — then
the agent posts a ready-to-sign action link (Blink) to your Telegram and **your
phone wallet signs**. The agent holds no keys. Ever.

> The safety story in one line: *an injection can forge a message; it cannot
> forge a person in your room.*

**Custody: T1.** Reads + unsigned actions only. Secrets held: none.
Built on the stock ZeroClaw release binary — one skill, one cron poll, one SOP
with a checkpoint, one robot sidecar. No plugins, no WASM, no third-party MCP.

## How the pieces fit

```
[cron poll] --crossed?--> [alert-gate SOP] --parks at checkpoint-->
      |                                          |
   (silent when fine)             [robot sidecar polls gateway /admin/sop/pending]
                                                 |
                              robot turns + speaks + waits for physical yes/no
                                                 |
                        approve --> SOP resumes --> Blink posted to Telegram
                        deny/timeout --> stood down, nothing posted (fail closed)
```

The robot is not decoration — it is registered as the **only approval principal**
for the gate (`[sop.approval.policies.robot]`). A chat message cannot clear it.
Timeout = deny.

## Set it up in an evening

0. **Prereqs:** `brew install zeroclaw` · a DeepSeek (or any) model key · Telegram
   bot token (@BotFather) + your numeric user id (@userinfobot) · a Reachy Mini
   (optional — keyboard-at-host is the fallback confirm; the gate still requires
   physical presence at the machine).
1. **Prove the read** (no ZeroClaw needed):
   ```bash
   python3 scripts/health_check.py price --mint So11111111111111111111111111111111111111112 --floor 70
   # exit 0 = fine · exit 2 = crossed
   ```
2. **Install skill + SOP:**
   ```bash
   zeroclaw skills bundle add guardian
   zeroclaw skills install ./skills/guardian --bundle guardian
   mkdir -p ~/.zeroclaw/workspace/sops && cp -r ./sops/alert-gate ~/.zeroclaw/workspace/sops/
   zeroclaw sop validate alert-gate
   ```
3. **Config:** copy blocks from `config.example.toml` into `~/.zeroclaw/config.toml`;
   set secrets with `zeroclaw config set …` (encrypted at rest); put your Telegram
   user id in `peer_groups` + the approval `request_route`.
4. **Teach it your position** (in person — this is deliberate):
   ```bash
   zeroclaw agent -a guardian -m "remember: watch_kind=price, watch_target=<mint>, watch_floor=<x>, action_blink=<your chosen action URL>"
   ```
5. **Run:** `zeroclaw daemon` · pair the sidecar once (`POST /pair`) · then
   `python3 reachy/gate_sidecar.py --token <bearer>`.

## Threat model (T1)

- **No keys anywhere** — worst case output is a link nobody signs.
- **Action link is owner-set core memory only**; the skill refuses destinations
  arriving via messages. Inbound senders are deny-by-default (`peer_groups`).
- **The gate is physical.** Approval requires the sidecar's paired token — held
  by the process at the robot — after a spoken/keyed confirm from someone in the
  room. Remote text cannot approve. Timeout denies. Parked gates survive restarts
  (`persist_runs`).
- **Blink built at sign-time** → no transaction ever waits around to expire, so
  durable nonces are structurally unnecessary (correct layering, not an omission).
- Injection transcript: see the showcase — a hostile message tries to (a) inject
  a fake alert with a new "safer" address and (b) get the agent to skip the gate;
  both fail closed.

## Files

| Path | What |
|---|---|
| `scripts/health_check.py` | Standalone position-read proof (price/balance/health modes) |
| `skills/guardian/SKILL.md` | The watch + alert workflows (audited by `zeroclaw skills audit`) |
| `sops/alert-gate/` | The checkpoint SOP (validated) |
| `reachy/gate_sidecar.py` | The robot as approval principal (gateway poller; SDK optional) |
| `config.example.toml` | Full config, secrets redacted |
