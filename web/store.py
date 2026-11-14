"""Where runs and retrieved data live.

Two kinds of data, two lifetimes:
  * Run state (one per user request): status, append-only event log, final result.
      local: data/runs/<run_id>/run.json        AWS: DynamoDB table `runs` (pk=run_id) + events (pk=run_id, sk=seq)
  * Retrieved data (shared by all runs, user-independent): per-asset filings reports, per-country reports.
      local: data/cache/<kind>/<key>.json         AWS: S3 s3://<bucket>/cache/<kind>/<key>.json
    Keyed by as_of so a cached report is never reused for an earlier date (no look-ahead).
  * Precomputed scenarios: data/scenarios/latest.json   AWS: S3 scenarios/<week>.json (weekly EventBridge job)

Only the local backend exists for now. A DynamoDB/S3 backend implements the same methods.
"""
import json
import threading
import time
import uuid
from pathlib import Path

ROOT = Path("data")


class LocalRunStore:
    def __init__(self, root: Path = ROOT / "runs"):
        self.root, self._runs, self._lock = root, {}, threading.Lock()

    def create(self, request: dict) -> str:
        run_id = uuid.uuid4().hex[:12]
        self._runs[run_id] = {"id": run_id, "created": time.time(), "status": "queued",
                              "request": request, "events": [], "result": None, "error": None}
        self._save(run_id)
        return run_id

    def get(self, run_id: str) -> dict | None:
        if run_id not in self._runs:
            p = self.root / run_id / "run.json"
            if not p.exists():
                return None
            self._runs[run_id] = json.loads(p.read_text())
        return self._runs[run_id]

    def append_event(self, run_id: str, **event) -> None:
        with self._lock:
            run = self._runs[run_id]
            event.update(seq=len(run["events"]) + 1, t=round(time.time() - run["created"], 2))
            run["events"].append(event)
        self._save(run_id)

    def events_after(self, run_id: str, seq: int) -> list[dict]:
        return self.get(run_id)["events"][seq:]

    def set(self, run_id: str, **fields) -> None:
        self._runs[run_id].update(fields)
        self._save(run_id)

    def _save(self, run_id: str) -> None:
        d = self.root / run_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "run.json").write_text(json.dumps(self._runs[run_id], default=str))


class LocalCache:
    """Retrieved-data cache shared across runs (S3 in production)."""

    def __init__(self, root: Path = ROOT / "cache"):
        self.root = root

    def _path(self, kind: str, key: str) -> Path:
        return self.root / kind / f"{key}.json"

    def get(self, kind: str, key: str) -> dict | None:
        p = self._path(kind, key)
        return json.loads(p.read_text()) if p.exists() else None

    def put(self, kind: str, key: str, value: dict) -> None:
        p = self._path(kind, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value, default=str))


runs = LocalRunStore()
cache = LocalCache()
