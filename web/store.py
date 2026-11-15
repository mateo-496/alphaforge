"""Run state, one per user request: status, append-only event log, final result -> data/runs/<id>/run.json.
Shared data (prices, filings, GPR, scenarios) lives in core.storage, local or S3."""
import hashlib
import json
import logging
import re
import threading
import time
import uuid
from pathlib import Path

from core import config

ROOT = config.DATA_DIR
_SAVE_RETRIES = 8          # ~0.7 s total backoff before giving up on one write
log = logging.getLogger(__name__)


def analysis_key(request: dict) -> str:
    """Identity of an analysis: holdings (order-free), profile, analysis date, scenario country."""
    pf = request["portfolio"]
    ident = {"holdings": sorted((h["ticker"], round(h["weight"], 6)) for h in pf["holdings"]),
             "base_currency": pf.get("base_currency"), "profile": request["profile"], "as_of": request["as_of"],
             "scenario_country": request.get("scenario_country")}
    raw = json.dumps(ident, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


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

    def remember(self, key: str, run_id: str) -> None:
        """Point an analysis key at the run that answers it (data/runs/index/<key>.json)."""
        try:
            d = self.root / "index"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{key}.json").write_text(json.dumps({"run_id": run_id, "at": time.time()}))
        except OSError as e:
            log.warning("run index not written (%s)", e)

    def lookup(self, key: str) -> str | None:
        """The run last remembered for this analysis key, if any."""
        p = self.root / "index" / f"{key}.json"
        try:
            return json.loads(p.read_text())["run_id"] if re.fullmatch(r"[0-9a-f]{32}", key) and p.exists() else None
        except (OSError, ValueError, KeyError):
            return None

    def events_after(self, run_id: str, seq: int) -> list[dict]:
        return self.get(run_id)["events"][seq:]

    def set(self, run_id: str, **fields) -> None:
        with self._lock:
            self._runs[run_id].update(fields)
            self._save(run_id)

    def _save(self, run_id: str) -> None:   # called with the lock held; atomic replace, never a half-written file
        """Persist a run. The in-memory copy is authoritative, so a failed write is logged, never raised.

        On Windows, os.replace fails with PermissionError (WinError 5) while another process
        (antivirus, search indexer, OneDrive) briefly holds run.json open; retry with backoff.
        """
        d = self.root / run_id
        try:
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / "run.json.tmp"
            tmp.write_text(json.dumps(self._runs[run_id], default=str))
            for attempt in range(_SAVE_RETRIES):
                try:
                    tmp.replace(d / "run.json")
                    return
                except PermissionError:
                    if attempt == _SAVE_RETRIES - 1:
                        raise
                    time.sleep(0.02 * (attempt + 1))
        except OSError as e:
            log.warning("run %s: could not persist run.json (%s); continuing in memory", run_id, e)


runs = LocalRunStore()
