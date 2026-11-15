"""Run state, one per user request: status, append-only event log, final result -> data/runs/<id>/run.json.
Shared data (prices, filings, GPR, scenarios) lives in core.storage, local or S3."""
import json
import re
import threading
import time
import uuid
from pathlib import Path

ROOT = Path("data")


class LocalRunStore:
    def __init__(self, root: Path = ROOT / "runs"):
        self.root, self._runs, self._lock = root, {}, threading.RLock()

    def create(self, request: dict) -> str:
        run_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._runs[run_id] = {"id": run_id, "created": time.time(), "status": "queued",
                                  "request": request, "events": [], "result": None, "error": None}
            self._save(run_id)
        return run_id

    def get(self, run_id: str) -> dict | None:
        if not re.fullmatch(r"[0-9a-f]{12}", run_id or ""):   # ids come from URLs
            return None
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
        with self._lock:
            self._runs[run_id].update(fields)
            self._save(run_id)

    def _save(self, run_id: str) -> None:   # called with the lock held; atomic replace, never a half-written file
        d = self.root / run_id
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "run.json.tmp"
        tmp.write_text(json.dumps(self._runs[run_id], default=str))
        tmp.replace(d / "run.json")


runs = LocalRunStore()
