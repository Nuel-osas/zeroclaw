#!/usr/bin/env python3
"""Guardian robot gate — the Reachy Mini as a ZeroClaw approval principal.

Polls the ZeroClaw gateway for SOP runs parked at the `robot` checkpoint.
When one appears: the robot turns toward you, speaks the pending alert aloud,
and waits for a PHYSICAL confirmation. On confirm it POSTs approve to the
gateway; on deny/timeout it POSTs deny. A chat message cannot clear the gate —
that is the entire point.

Confirmation modalities (first available wins):
  1. Reachy Mini SDK ASR — spoken "yes"/"approve" vs "no"/"deny"
  2. Keyboard at the robot's host — [y]/[n] with countdown (still physical presence)
Timeout always = DENY (fail closed).

Pairing: the gateway requires a bearer token.
  curl -X POST http://127.0.0.1:42617/pair -H "X-Pairing-Code: <code>"  → {"token": ...}
Run:
  python3 gate_sidecar.py --token <bearer> [--gateway http://127.0.0.1:42617] [--timeout 90]

Stdlib only; Reachy SDK optional (motion/speech degrade gracefully, same wrapper
pattern as the upnepa sidecar).
"""
import argparse, json, select, shutil, subprocess, sys, time, urllib.request

POLL_SECS = 3


def speak(text):
    if sys.platform == "darwin" and shutil.which("say"):
        subprocess.run(["say", text], check=False)
    elif shutil.which("espeak"):
        subprocess.run(["espeak", text], check=False)
    else:
        print(f"[voice] {text}")


class Robot:
    def __init__(self):
        self.mini = None
        try:
            from reachy_mini import ReachyMini  # type: ignore
            self.mini = ReachyMini()
            print("[reachy] connected")
        except Exception as e:
            print(f"[reachy] not available ({e}) — host speech/keys fallback")

    def _try(self, name, *a, **k):
        if self.mini is None: return False
        try:
            fn = getattr(self.mini, name, None)
            if fn is None: return False
            fn(*a, **k); return True
        except Exception as e:
            print(f"[reachy] {name} failed: {e}"); return False

    def attend(self):
        # face the owner: verify method names against your SDK build
        if not self._try("play_emotion", "curious"):
            self._try("goto_posture", "default")

    def ack_yes(self): self._try("play_emotion", "happy")
    def ack_no(self):  self._try("play_emotion", "sad")

    def listen_yes_no(self, timeout_s):
        """SDK ASR if present; returns True/False/None(no ASR)."""
        if self.mini is None: return None
        try:
            rec = getattr(self.mini, "listen", None)
            if rec is None: return None
            heard = rec(timeout=timeout_s)  # ROBOT ASR: verify signature on your SDK
            if not heard: return False
            heard = heard.lower()
            if any(w in heard for w in ("yes", "approve", "confirm", "go ahead")): return True
            if any(w in heard for w in ("no", "deny", "stop", "stand down")):      return False
            return False
        except Exception as e:
            print(f"[reachy] ASR failed: {e}"); return None


def keyboard_confirm(timeout_s):
    print(f"[gate] press y to APPROVE, n to DENY ({timeout_s}s, silence = deny): ", end="", flush=True)
    end = time.time() + timeout_s
    while time.time() < end:
        r, _, _ = select.select([sys.stdin], [], [], 0.5)
        if r:
            ch = sys.stdin.readline().strip().lower()
            return ch.startswith("y")
    print("\n[gate] timeout")
    return False


def api(base, token, method, path, body=None):
    req = urllib.request.Request(
        base + path, method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", default="http://127.0.0.1:42617")
    ap.add_argument("--token", required=True)
    ap.add_argument("--timeout", type=int, default=90)
    a = ap.parse_args()

    robot = Robot()
    seen = set()
    print(f"[gate] watching {a.gateway}/admin/sop/pending")
    while True:
        try:
            pending = api(a.gateway, a.token, "GET", "/admin/sop/pending")
        except Exception as e:
            print(f"[gate] gateway unreachable: {e}"); time.sleep(POLL_SECS); continue

        runs = pending if isinstance(pending, list) else pending.get("runs", pending.get("pending", []))
        for run in runs or []:
            rid = run.get("run_id") or run.get("id")
            if not rid or rid in seen: continue
            seen.add(rid)
            summary = (run.get("summary") or run.get("step") or
                       json.dumps(run)[:140])
            print(f"[gate] PENDING {rid}: {summary}")

            robot.attend()
            speak(f"Attention. Position alert. {summary}. Say yes to approve, no to stand down.")

            decision = robot.listen_yes_no(a.timeout)
            if decision is None:                       # no ASR on this build
                decision = keyboard_confirm(a.timeout)

            body = {"run_id": rid}
            if decision:
                robot.ack_yes(); speak("Approved. Sending the action to your phone.")
                api(a.gateway, a.token, "POST", "/admin/sop/approve", body)
                print(f"[gate] APPROVED {rid}")
            else:
                robot.ack_no(); speak("Standing down. Nothing sent.")
                api(a.gateway, a.token, "POST", "/admin/sop/deny", body)
                print(f"[gate] DENIED {rid}")
        time.sleep(POLL_SECS)


if __name__ == "__main__":
    main()
