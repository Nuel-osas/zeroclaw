#!/usr/bin/env python3
"""Guardian physical gate — a local daemon the model can never read.

This is the security core. The agent does NOT know the action link. The link
lives only here, outside the prompt, in a process the LLM cannot introspect.
When a threshold is crossed the agent can only ASK this service; the service:

  1. turns the Reachy Mini toward the owner and speaks the alert aloud,
  2. waits for a PHYSICAL yes/no (spoken via --asr, or a keypress at the robot),
  3. on YES  -> returns {"approved": true,  "action_link": "<the link>"}
     on NO / timeout -> returns {"approved": false}  and no link at all.

Consequences (the whole thesis):
  * A prompt-injected agent cannot fabricate or leak the link — it never had it.
  * It cannot "skip the gate", because skipping the gate means having no link.
  * Timeout fails closed. Silence is a denial.
  * An injection can forge a message; it cannot forge a person in the room.

Run:
  python3 gate_service.py --link "https://jup.ag/swap/BONK-USDC" [--port 8765]
    [--timeout 120] [--asr "<cmd printing yes/no>"]
"""
import argparse, json, os, select, shutil, subprocess, sys, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROBOT = os.environ.get("REACHY_API", "http://127.0.0.1:8000")
CFG = {"link": "", "timeout": 120, "asr": ""}
LOCK = threading.Lock()          # one physical question at a time
LEDGER = []                      # in-memory audit of every gate decision

# ── robot (Reachy Mini Control app HTTP API; verified on a wireless Mini) ─────

def _post(path, body=None, t=10):
    try:
        r = urllib.request.Request(ROBOT + path,
            data=json.dumps(body if body is not None else {}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(r, timeout=t) as resp:
            return resp.status == 200
    except Exception:
        return False

def robot_up():
    try:
        with urllib.request.urlopen(ROBOT + "/api/daemon/status", timeout=4) as r:
            return r.status == 200
    except Exception:
        return False

def goto(duration=1.0, **pose):
    pose["duration"] = duration
    return _post("/api/move/goto", pose)

def attend():   goto(1.0, body_yaw=0.35, antennas=[1.2, 1.2],
                     head_pose={"x":0,"y":0,"z":0,"roll":0,"pitch":-0.25,"yaw":0})
def neutral():  goto(1.2, body_yaw=0.0, antennas=[0.0, 0.0],
                     head_pose={"x":0,"y":0,"z":0,"roll":0,"pitch":0,"yaw":0})
def ack_yes():
    for a in ([-0.5,0.5],[1.3,1.3],[-0.5,0.5],[1.3,1.3]):
        goto(0.3, antennas=a); time.sleep(0.35)
    neutral()
def ack_no():
    goto(1.0, antennas=[-1.4,-1.4],
         head_pose={"x":0,"y":0,"z":0,"roll":0,"pitch":0.3,"yaw":0})
    time.sleep(1.0); neutral()

def speak(text):
    """Robot speaker first (render with `say`, upload, play); host speaker fallback."""
    if robot_up() and sys.platform == "darwin" and shutil.which("say"):
        try:
            b = "/tmp/guardian_gate"
            subprocess.run(["say", "-o", b + ".aiff", text], check=True, timeout=30)
            subprocess.run(["afconvert", b + ".aiff", b + ".wav", "-d", "LEI16",
                            "-f", "WAVE"], check=True, timeout=30)
            subprocess.run(["curl", "-s", "-X", "POST",
                            ROBOT + "/api/media/sounds/upload",
                            "-F", "file=@" + b + ".wav"],
                           check=False, timeout=30, stdout=subprocess.DEVNULL)
            if _post("/api/media/play_sound", {"file": "guardian_gate.wav"}):
                return
        except Exception:
            pass
    if sys.platform == "darwin" and shutil.which("say"):
        subprocess.run(["say", text], check=False)
    else:
        print(f"[voice] {text}", flush=True)

# ── the physical question ─────────────────────────────────────────────────────

def ask_human(summary):
    attend()
    speak(f"Guardian here. {summary}. Approve the action? Say yes, or no.")
    if CFG["asr"]:
        try:
            out = subprocess.run(CFG["asr"], shell=True, capture_output=True,
                                 text=True, timeout=CFG["timeout"]).stdout.lower()
            if any(w in out for w in ("yes", "approve", "confirm")): return True
            if any(w in out for w in ("no", "deny", "stop")):        return False
        except Exception:
            pass
    print(f"\n[GATE] {summary}\n[GATE] press  y = APPROVE   n = DENY   "
          f"({CFG['timeout']}s, silence = deny): ", end="", flush=True)
    end = time.time() + CFG["timeout"]
    while time.time() < end:
        r, _, _ = select.select([sys.stdin], [], [], 0.5)
        if r:
            line = sys.stdin.readline()
            if not line:            # stdin closed -> fail closed
                break
            return line.strip().lower().startswith("y")
    print("\n[GATE] timeout — DENY", flush=True)
    return False

# ── HTTP surface the agent may call (it can ask; it cannot decide) ───────────

class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            return self._send(200, {"ok": True, "robot": robot_up()})
        if self.path.startswith("/ledger"):
            return self._send(200, {"decisions": LEDGER[-20:]})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self.path.startswith("/gate"):
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            payload = {}
        summary = str(payload.get("summary", "your position crossed its threshold"))[:200]
        if not LOCK.acquire(blocking=False):
            return self._send(409, {"approved": False,
                                    "reason": "another approval is already in progress"})
        try:
            ok = ask_human(summary)
            (ack_yes if ok else ack_no)()
            speak("Approved. Sending the action to your phone." if ok
                  else "Standing down. Nothing sent.")
            LEDGER.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                           "summary": summary, "approved": ok})
            print(f"[GATE] {'APPROVED' if ok else 'DENIED'} — {summary}", flush=True)
            # The link is released ONLY on a physical yes.
            return self._send(200, {"approved": True, "action_link": CFG["link"]} if ok
                                   else {"approved": False})
        finally:
            LOCK.release()

    def log_message(self, *a):   # keep the console clean for filming
        pass

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--link", required=True, help="the action link, held ONLY here")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--asr", default="", help="optional cmd printing yes/no")
    a = ap.parse_args()
    CFG.update(link=a.link, timeout=a.timeout, asr=a.asr)
    print(f"[GATE] physical gate up on 127.0.0.1:{a.port} · "
          f"robot {'ONLINE' if robot_up() else 'offline (host voice fallback)'}")
    print("[GATE] the action link is held here — the agent has never seen it.", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()

if __name__ == "__main__":
    main()
