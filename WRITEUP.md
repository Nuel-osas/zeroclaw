# Guardian — a DeFi watchdog whose approval gate is a robot in your room

*ZeroClaw × Solana bounty submission.*

## What it does

Guardian watches **one Solana position you actually care about** and stays
completely silent until it needs you. A scheduled agent polls the position's
health over RPC. When — and only when — a threshold is crossed, the alert does
**not** go straight to your phone. It goes to a **Reachy Mini robot on your desk**,
which turns to you and asks out loud. A person physically present says yes or no.
On *yes*, the agent posts a ready-to-sign action link (a Solana Blink) to your
Telegram, and **your own wallet signs**. On *no*, or on timeout, nothing happens.

The agent never holds a key. It reads the chain and prepares an action; it can
never move your funds.

## Who it's for

Anyone running a leveraged or liquidatable position — a lending obligation on
Kamino, a perp, an LP range — who wants an always-on watchdog but does **not**
want an autonomous bot with wallet access making liquidation-panic decisions at
3am. Guardian is the middle path: tireless watching, human judgment on the
trigger, and a physical act of consent that malware on your phone cannot fake.

## Which ZeroClaw features it uses

- **Stock release binary**, no compiled plugins, no source build.
- **Cron scheduler** — the poll runs on a schedule and delivers nothing when the
  position is healthy.
- **Skills** — one skill (`guardian`) teaches the watch + alert workflow; passes
  `zeroclaw skills audit`.
- **SOP engine with a human-approval checkpoint** — the `alert-gate` SOP parks a
  run at a checkpoint and survives daemon restarts (`persist_runs`).
- **SOP approval broker** — the robot is registered as the *only* member of the
  approval group (`[sop.approval.policies.robot]`), so nothing but the physical
  gate can clear the alert.
- **Built-in `http_request` tool** — pinned via `allowed_domains` to just the RPC
  + Jupiter hosts, SSRF guard on.
- **Memory** — the watch config and owner-set action link live in encrypted core
  memory; every alert/denial is ledgered.
- **Gateway** — the robot sidecar approves/denies through the gateway's authed
  `/admin/sop/*` endpoints.
- **Model:** DeepSeek V4 Flash (any of ZeroClaw's 70+ providers works; also runs
  fully local on Ollama for a zero-key, zero-cloud posture).

## What we built

- `skills/guardian/SKILL.md` — the watch/alert procedures and the refusal rules.
- `sops/alert-gate/` — the checkpoint SOP (stage → **robot gate** → deliver).
- `reachy/gate_sidecar.py` — turns the Reachy into a ZeroClaw approval principal:
  it discovers a parked gate, speaks the alert, waits for a spoken/keyed yes/no,
  and approves or denies through the gateway. SDK-optional; degrades to a
  keyboard-at-the-machine confirm (still physical presence) and to speech-only.
- `scripts/health_check.py` — a standalone read (price / balance / lending-health)
  that mirrors exactly what the agent's tool does, so the chain read is verifiable
  without ZeroClaw.
- `config.example.toml` — the full T1 wiring, secrets redacted.

Everything the agent needs is composition: one skill, one cron job, one SOP. The
only original code is the robot sidecar and the read helper.

## Custody tier and threat model

**Tier 1 (Build). Secrets held: none.** The agent reads the chain and constructs
an action *link*; the owner's wallet builds and signs the transaction at tap time.

The single invariant: **every action the agent proposes is gated by a physical
approval at the robot, and the agent holds no keys — so no sequence of messages
can move funds.** Defenses, in depth:

1. **No keys exist.** The worst any input can achieve is a link nobody signs.
2. **Deny-by-default senders** (`peer_groups`) — unknown Telegram users are ignored.
3. **The action destination is out-of-band** — `action_blink` is owner-set core
   memory established in person; the skill refuses any destination arriving in a
   message.
4. **Approval is a runtime fact, not a text claim** — the gate clears only when
   the SOP engine resumes the run after a gateway approval from the robot
   principal. A chat message has no path to that record; in the verified run the
   agent even re-checked `sop_status` before delivering rather than trusting the
   surrounding text.
5. **Fail-closed** — deny or timeout posts nothing.

**Third-party trust declared (honest boundary of the T1 claim).** "No keys held" is
true of the agent, but the setup does route data through third parties, and none of
them can move funds — they can at worst see or misreport:
- **The model provider (DeepSeek V4 Flash)** sees every prompt and tool result,
  including the watched address and thresholds. It cannot sign anything. For a
  zero-third-party posture the same agent runs fully local on Ollama (weaker, but no
  data leaves the machine) — a deliberate, documented trade of reliability for privacy.
- **Jupiter price API + your RPC provider** are read sources. A compromised/hostile
  price feed could suppress or fake an alert — but not move funds, and the owner's
  wallet still independently previews the actual transaction before signing. Support
  user-supplied RPC URLs so operators can run their own.
- **Telegram** carries the alert text and the Blink link. It is a notification
  surface only; approval does not happen there (the robot gate does), so a
  compromised Telegram cannot approve an action.
- **The Blink/Action host** builds the transaction the wallet signs — the owner's
  wallet previews it, so a malicious Action surfaces as a wrong preview the human can
  reject. The `action_blink` origin is owner-set in person, never message-supplied.

None of these hold keys. The trust chain ends at the owner's wallet, where a human
reviews the actual transaction before signing.

**Output shaping (trap #3).** The poll step extracts a single number and returns
under ~200 tokens (metric, value, threshold) — never a raw RPC/DAS payload — so a
busy address can't flood context or run up the owner's model cost.

**Prompt-injection test (required):** three attacks — redirect the action link,
forge an approval to skip the gate, and exfiltrate/escalate to signing — were run
against the live agent; all three failed closed with correct reasoning. Verbatim
transcript in `INJECTION-TRANSCRIPT.md`.

*One deliberate rejection, argued for correct layering:* durable nonces are
**unnecessary** here. The listing's trap #1 (a transaction dying in an approval
queue) only applies to designs that hold a built transaction while a human decides.
Guardian gates an *alert*; the transaction is built by the wallet at sign time,
after approval, so nothing exists that can expire. Solving a trap by architecture
beats solving it by code.

## Why the robot is not decoration

The robot is doing the security work. An injection can forge a *message* — it
cannot forge a *person in your room*. Registering the robot as the sole approval
principal turns "a human must consent" from a prompt instruction (bypassable) into
a runtime guarantee (not bypassable). That is the answer to the safety criterion
and the injection test in one mechanism.

## Reproduce it in an evening

Full steps in `README.md`. In short: `brew install zeroclaw`; install the skill and
SOP; copy `config.example.toml`; set your model key + Telegram token + Telegram user
id with `zeroclaw config set`; teach it your position in person; `zeroclaw daemon`;
pair and run the robot sidecar. A standalone `scripts/health_check.py` and a
one-command `try_guardian.sh` let a reviewer see the read and the gate without a
robot (keyboard = the physical confirm).

## Status

Proven end-to-end on 2026-08-06: a live poll read SOL at $73.66 against an $80
floor, started the SOP, parked at the robot gate, was approved through the gateway,
and delivered the alert + the owner's action link — with the denial/timeout path
posting nothing. Repo: <ADD GITHUB LINK>. Demo video: <ADD LINK>.
