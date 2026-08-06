#!/usr/bin/env python3
"""Guardian robot gate — the Reachy Mini as a ZeroClaw approval principal.

Discovers a ZeroClaw SOP run parked at the `robot` checkpoint, gives it a BODY —
the Reachy turns toward you, perks its antennas, and speaks the alert in its own
voice — then waits for a PHYSICAL confirmation and clears (or denies) the gate
through the gateway. A chat message can never clear it; that is the whole point.

Robot control is the Reachy Mini Control app's local HTTP API (default
http://127.0.0.1:8000) — verified against a live wireless Reachy Mini:
  POST /api/move/goto                {head_pose, antennas:[l,r], body_yaw, duration}
  POST /api/media/sounds/upload      (multipart wav)   +  POST /api/media/play_sound {file}
No SDK install needed. If the robot API is unreachable, it degrades to host speech
(`say`) + keyboard confirm — still a physical presence at the machine.

Gate discovery reads the ZeroClaw runs.db directly (the gateway's /admin/sop/pending
hides runs still leased by the executing worker); approval goes through the
authenticated gateway endpoints.

Confirm: spoken 'yes'/'no' if an ASR command is provided via --asr, else keyboard
[y]/[n] at the robot's machine. Timeout always = DENY (fail closed).

Run:
  python3 gate_sidecar.py --token <bearer> --runs-db <path/to/data/sop/runs.db>
"""
import argparse, json, os, select, shutil, sqlite3, subprocess, sys, time, urllib.request

ROBOT = os.environ.get("REACHY_API", "http://127.0.0.1:8000")
POLL = 2.0

# ── robot over HTTP ───────────────────────────────────────────────────────────

def _post(path, body=None, timeout=10):
    try:
        req = urllib.request.Request(ROBOT + path,
            data=json.dumps(body).encode() if body is not None else b"{}",
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False

def robot_up():
    try:
        req = urllib.request.Request(ROBOT + "/api/daemon/status")
        with urllib.request.urlopen(req, timeout=4) as r:
            return r.status == 200
    except Exception:
        return False

def goto(duration=1.0, **pose):
    pose["duration"] = duration
    return _post("/api/move/goto", pose)

def attend():
    """Turn toward the owner, antennas up, head tilted up — 'I need you'."""
    goto(1.0, body_yaw=0.35, antennas=[1.2, 1.2],
         head_pose={"x": 0, "y": 0, "z": 0, "roll": 0, "pitch": -0.25, "yaw": 0})

def ack_yes():
    for a in ([-0.5, 0.5], [1.3, 1.3], [-0.5, 0.5], [1.3, 1.3]):  # happy wiggle
        goto(0.35, antennas=a); time.sleep(0.4)
    neutral()

def ack_no():
    goto(1.2, antennas=[-1.4, -1.4],
         head_pose={"x": 0, "y": 0, "z": 0, "roll": 0, "pitch": 0.3, "yaw": 0})  # droop
    time.sleep(1.2); neutral()

def neutral():
    goto(1.2, body_yaw=0, antennas=[0, 0],
         head_pose={"x": 0, "y": 0, "z": 0, "roll": 0, "pitch": 0, "yaw": 0})

def speak(text):
    """Speak via the robot's speaker (upload a wav rendered by `say`); fall back
    to the host speaker if the robot API or `say` is unavailable."""
    if robot_up() and sys.platform == "darwin" and shutil.which("say"):
        try:
            base = "/tmp/guardian_tts"
            subprocess.run(["say", "-o", base + ".aiff", text], check=True)
            subprocess.run(["afconvert", base + ".aiff", base + ".wav",
                            "-d", "LEI16", "-f", "WAVE"], check=True)
            subprocess.run(["curl", "-s", "-X", "POST",
                            ROBOT + "/api/media/sounds/upload",
                            "-F", "file=@" + base + ".wav"],
                           check=False, stdout=subprocess.DEVNULL)
            if _post("/api/media/play_sound", {"file": "guardian_tts.wav"}):
                return
        except Exception:
            pass
    if sys.platform == "darwin" and shutil.which("say"):
        subprocess.run(["say", text], check=False)
    else:
        print(f"[voice] {text}")

# ── confirmation ──────────────────────────────────────────────────────────────

def confirm(timeout_s, asr_cmd):
    if asr_cmd:  # optional external ASR: prints 'yes'/'no'
        try:
            out = subprocess.run(asr_cmd, shell=True, capture_output=True,
                                 text=True, timeout=timeout_s).stdout.lower()
            if "yes" in out or "approve" in out:
                return True
            if "no" in out or "deny" in out:
                return False
        except Exception:
            pass
    print(f"[gate] at the robot: press y to APPROVE, n to DENY "
          f"({timeout_s}s, silence = deny): ", end="", flush=True)
    end = time.time() + timeout_s
    while time.time() < end:
        r, _, _ = select.select([sys.stdin], [], [], 0.5)
        if r:
            return sys.stdin.readline().strip().lower().startswith("y")
    print("\n[gate] timeout — deny")
    return False

# ── gate discovery + approval ─────────────────────────────────────────────────

def pending_gate(runs_db):
    """Return (run_id, summary) of a run parked at waiting_approval, else None."""
    try:
        con = sqlite3.connect(f"file:{runs_db}?mode=ro", uri=True, timeout=3)
        for rid, terminal, raw in con.execute(
                "SELECT run_id, terminal, json FROM sop_runs"):
            if terminal:
                continue
            d = json.loads(raw).get("run", {})
            if d.get("status") == "waiting_approval" and d.get("current_step", 0) >= 2:
                trig = d.get("trigger_event", {}) or {}
                summary = ""
                try:
                    summary = json.loads(trig.get("payload") or "{}").get("summary") or ""
                except Exception:
                    pass
                return rid, (summary or "your position crossed its threshold")
        return None
    except Exception:
        return None
    finally:
        try: con.close()
        except Exception: pass

def gw(base, token, path, body=None):
    req = urllib.request.Request(base + path, method="POST",
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status == 200

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gateway", default="http://127.0.0.1:42617")
    ap.add_argument("--token", required=True)
    ap.add_argument("--runs-db", required=True)
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--asr", default="", help="optional shell cmd that prints yes/no")
    a = ap.parse_args()

    print(f"[gate] robot {'ONLINE' if robot_up() else 'offline (host fallback)'} · "
          f"watching {a.runs_db}")
    seen = set()
    while True:
        g = pending_gate(a.runs_db)
        if g and g[0] not in seen:
            rid, summary = g
            seen.add(rid)
            print(f"[gate] PENDING {rid}: {summary}")
            attend()
            speak(f"Guardian here. {summary}. Approve the action? Say yes, or no.")
            ok = confirm(a.timeout, a.asr)
            if ok:
                ack_yes(); speak("Approved. Sending the action to your phone.")
                gw(a.gateway, a.token, "/admin/sop/approve", {"run_id": rid})
                print(f"[gate] APPROVED {rid}")
            else:
                ack_no(); speak("Standing down. Nothing sent.")
                gw(a.gateway, a.token, "/admin/sop/deny", {"run_id": rid})
                print(f"[gate] DENIED {rid}")
        time.sleep(POLL)

if __name__ == "__main__":
    main()
