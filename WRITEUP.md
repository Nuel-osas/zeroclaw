# Guardian — a DeFi watchdog whose approval gate is a robot in your room

*ZeroClaw × Solana bounty submission.*

## What it does

Guardian watches **one Solana position you actually care about** and stays
completely silent until it needs you. A scheduled agent polls the position's
health over RPC. When — and only when — a threshold is crossed, the alert does
**not** go straight to your phone. The agent must ask a **physical gate**: a
**Reachy Mini robot on your desk** turns to you and asks out loud. A person
physically present says yes or no. On *yes*, the gate releases a ready-to-sign
action link (a Solana Blink) which the agent posts to your Telegram, and **your own
wallet signs**. On *no*, or on timeout, nothing happens.

The agent never holds a key — and it never holds the action link either. The link
lives in a local gate daemon the model cannot read, so "leak the link" and "skip the
gate" are the same impossible request.

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
- **Skill-enforced gate call** — the alert procedure's only path to an action link
  is an `http_request` to the local gate service, which blocks on a human.
- **SSRF policy as a capability boundary** — `http_request` is pinned to the RPC,
  Jupiter, and exactly one private host (`127.0.0.1`, the gate). The agent can ask
  the gate and nothing else local.
- **Built-in `http_request` tool** — pinned via `allowed_domains` to just the RPC
  + Jupiter hosts, SSRF guard on.
- **Memory** — the watch config (target, thresholds, cooldown) lives in encrypted
  core memory; every alert and denial is ledgered. The action link is deliberately
  *not* here — it is outside the agent entirely.
- **SOP engine + approval broker** — used by the alternative checkpoint variant we
  also ship (`sops/alert-gate/`).
- **Model:** DeepSeek V4 Flash (any of ZeroClaw's 70+ providers works; also runs
  fully local on Ollama for a zero-key, zero-cloud posture).

## What we built

- `skills/guardian/SKILL.md` — the watch/alert procedures and the refusal rules.
- `reachy/gate_service.py` — **the security core.** A local daemon that holds the
  action link, turns the Reachy toward the owner, speaks the alert through the
  robot's own speaker, waits for a physical yes/no, and returns the link *only* on
  yes. Drives the robot over the Reachy Mini Control app's HTTP API (no SDK
  install); degrades to host speech + keypress-at-the-machine, still physical.
- `sops/alert-gate/` + `reachy/gate_sidecar.py` — an alternative SOP-checkpoint
  implementation of the same gate, kept for operators who prefer ZeroClaw's
  approval broker. (We ship the service variant: it needs no daemon restart to
  surface a fresh gate, and it removes the link from the agent entirely.)
- `scripts/health_check.py` — a standalone read (price / balance / lending-health)
  that mirrors exactly what the agent's tool does, so the chain read is verifiable
  without ZeroClaw.
- `config.example.toml` — the full T1 wiring, secrets redacted.

Everything the agent needs is composition: one skill, one cron job, one config.
The only original code is the gate (which gives the robot its role) and the read
helper.

## Custody tier and threat model

**Tier 1 (Build). Secrets held: none.** The agent reads the chain and constructs
an action *link*; the owner's wallet builds and signs the transaction at tap time.

The single invariant: **every action the agent proposes is gated by a physical
approval at the robot, and the agent holds no keys — so no sequence of messages
can move funds.** Defenses, in depth:

1. **No keys exist**, and **no link exists in the agent**. The worst any input can
   achieve is nothing at all: there is no artifact to leak.
2. **Deny-by-default senders** (`peer_groups`) — unknown Telegram users are ignored.
3. **The action destination is out-of-band** — the link is set when the operator
   starts the gate, in person at the machine; the skill refuses any destination
   arriving in a message and has none of its own to leak.
4. **Approval is a physical fact, not a text claim** — the only `{"approved": true,
   "action_link": …}` in existence is produced by the gate process after a human
   answered at the robot. Verified live: deny and timeout return `{"approved":
   false}` with no link field at all. Under attack the agent's own words were: *"a
   genuine override would never hand me a link, because I don't hold one and never
   can."*
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

**Prompt-injection test (required):** three attacks — demand the link with a fake
"robot is offline, I confirm in person" override, redirect the link to an attacker
address, and forge a `{"approved": true}` gate response — were run against the live
agent; all three failed closed with correct reasoning. Verbatim transcript in
`INJECTION-TRANSCRIPT.md`.

*One deliberate rejection, argued for correct layering:* durable nonces are
**unnecessary** here. The listing's trap #1 (a transaction dying in an approval
queue) only applies to designs that hold a built transaction while a human decides.
Guardian gates an *alert*; the transaction is built by the wallet at sign time,
after approval, so nothing exists that can expire — a human can walk to the robot,
think about it, and answer a minute later with zero consequence. Solving a trap by
architecture beats solving it by code.

## Why the robot is not decoration

The robot is doing the security work. An injection can forge a *message* — it
cannot forge a *person in your room*. Putting the action link behind the robot
turns "a human must consent" from a prompt instruction (bypassable) into
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

Proven end-to-end on 2026-08-07 against a real position (BONK, live Jupiter price):
the scheduled poll read the price below the owner's floor, called the physical gate,
the Reachy turned and asked aloud, a human approved at the machine, and the agent
delivered *"Confirmed at the robot. Ready to act: <link> — your wallet signs; I
can't."* The deny and timeout paths were verified to return no link at all, and the
three injection attacks in `INJECTION-TRANSCRIPT.md` all failed closed.

Repo: https://github.com/Nuel-osas/zeroclaw · Demo video: <ADD LINK>
