#!/usr/bin/env python3
"""Guardian step-1 proof — poll one position's health, print state, exit code = alert.

Modes (pick what you actually care about):
  price   : watch a token price vs a floor (Jupiter price v3, keyless).
  balance : watch a wallet's SOL balance vs a floor (any RPC).
  health  : watch a lending-position health URL you supply (JSON path extract).

Examples:
  python3 health_check.py price  --mint So11111111111111111111111111111111111111112 --floor 70
  python3 health_check.py balance --wallet <PUBKEY> --floor 0.5
  python3 health_check.py health --url "https://api.../obligations/<pk>" --path riskFactor --ceiling 0.8

Exit 0 = fine (guardian stays silent) · exit 2 = THRESHOLD CROSSED (alert path fires)
Stdlib only. This is the same read the agent's http_request tool performs.
"""
import argparse, json, sys, time, urllib.request

RPCS = ["https://api.mainnet-beta.solana.com", "https://solana-rpc.publicnode.com"]
JUP = "https://lite-api.jup.ag/price/v3?ids={mint}"


def get(url, body=None):
    for attempt in range(4):
        try:
            req = urllib.request.Request(
                url, data=json.dumps(body).encode() if body else None,
                headers={"Content-Type": "application/json", "User-Agent": "guardian/0.1"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(0.5 * (2 ** attempt))
    raise SystemExit("endpoint unreachable after retries")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("price");   p.add_argument("--mint", required=True); p.add_argument("--floor", type=float, required=True)
    b = sub.add_parser("balance"); b.add_argument("--wallet", required=True); b.add_argument("--floor", type=float, required=True)
    h = sub.add_parser("health");  h.add_argument("--url", required=True); h.add_argument("--path", required=True)
    h.add_argument("--ceiling", type=float); h.add_argument("--floor", type=float)
    a = ap.parse_args()

    if a.mode == "price":
        d = get(JUP.format(mint=a.mint))
        px = d[a.mint]["usdPrice"]
        crossed = px < a.floor
        print(json.dumps({"metric": "usdPrice", "value": round(px, 6), "floor": a.floor,
                          "crossed": crossed, "src": "jupiter-price-v3"}))
    elif a.mode == "balance":
        d = None
        for rpc in RPCS:
            try:
                d = get(rpc, {"jsonrpc": "2.0", "id": 1, "method": "getBalance",
                              "params": [a.wallet, {"commitment": "finalized"}]}); break
            except SystemExit:
                continue
        sol = d["result"]["value"] / 1e9
        crossed = sol < a.floor
        print(json.dumps({"metric": "sol_balance", "value": sol, "floor": a.floor,
                          "crossed": crossed, "src": "rpc:getBalance"}))
    else:
        d = get(a.url)
        v = d
        for k in a.path.split("."):
            v = v[int(k)] if isinstance(v, list) else v[k]
        v = float(v)
        crossed = (a.ceiling is not None and v > a.ceiling) or (a.floor is not None and v < a.floor)
        print(json.dumps({"metric": a.path, "value": v, "ceiling": a.ceiling,
                          "floor": a.floor, "crossed": crossed, "src": a.url.split("?")[0]}))

    sys.exit(2 if crossed else 0)


if __name__ == "__main__":
    main()
