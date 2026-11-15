"""Run the risk-ladder portfolios (examples/risk_ladder.json) through a running app, the way the UI does.

    uvicorn web.app:app --port 8080          # in another terminal
    python -m scripts.risk_ladder [--url http://127.0.0.1:8080] [--only L01-cad-cash,L05-us-megacap-tech]

Posts each portfolio to /runs, polls /runs/{id}/events until the run ends, then prints target vs. objective score
and writes outputs/risk_ladder.json. The run ids point at data/runs/<id>/run.json, which holds every measured
input of the formula (country splits, M_c, g_c, filing channels).
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
LADDER = ROOT / "examples" / "risk_ladder.json"
OUT = ROOT / "outputs" / "risk_ladder.json"


def submit(client: httpx.Client, spec: dict, profile: dict, as_of: str) -> str:
    form = {"mode": "weight", "as_of": as_of, "base_currency": "CAD", **{k: str(v) for k, v in profile.items()},
            "ticker": list(spec["holdings"]), "amount": [str(w) for w in spec["holdings"].values()]}
    r = client.post("/runs", data=form, follow_redirects=False)
    if r.status_code != 303:
        raise RuntimeError(f"{spec['id']}: HTTP {r.status_code}: {re.sub(r'<[^>]+>', ' ', r.text)[:300]}")
    return r.headers["location"].rsplit("/", 1)[-1]


def wait(client: httpx.Client, run_id: str, timeout_s: float) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        ev = client.get(f"/runs/{run_id}/events").json()
        if ev["status"] in ("done", "error"):
            return ev
        time.sleep(3)
    return {"status": "timeout", "error": f"no result after {timeout_s:.0f} s"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080")
    ap.add_argument("--only", default="")
    ap.add_argument("--timeout", type=float, default=900)
    a = ap.parse_args()
    lad = json.loads(LADDER.read_text(encoding="utf-8"))
    only = {x for x in a.only.split(",") if x}
    rows = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    with httpx.Client(base_url=a.url, timeout=60) as client:
        for spec in lad["portfolios"]:
            if only and spec["id"] not in only:
                continue
            t0 = time.time()
            run_id = submit(client, spec, lad["profile"], lad["as_of"])
            ev = wait(client, run_id, a.timeout)
            row = {"run_id": run_id, "target": spec["target"], "status": ev["status"], "error": ev.get("error"),
                   "seconds": round(time.time() - t0)}
            if ev["status"] == "done":
                res = json.loads((ROOT / "data" / "runs" / run_id / "run.json").read_text())["result"]
                row |= {"objective": res["objective"], "concern": res["score"], "inputs": res["inputs"],
                        "conf": res["conf"]}
            rows[spec["id"]] = row
            OUT.parent.mkdir(exist_ok=True)
            OUT.write_text(json.dumps(rows, indent=2), encoding="utf-8")
            print(f"{spec['id']:28s} target {spec['target']:3d}  objective {row.get('objective', '-')!s:>6}  "
                  f"concern {row.get('concern', '-')!s:>6}  {row['status']} {row['seconds']} s  {run_id}", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
