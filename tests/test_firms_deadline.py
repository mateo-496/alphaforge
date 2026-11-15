"""A stalled filings agent must not block the run: past the deadline the company is reported as timed out."""
import time

from web import firms


def test_deadline(monkeypatch):
    monkeypatch.setattr(firms, "WAIT_S", 1)

    def slow(t, s, as_of, emit):
        emit("start", t, s, None, False)
        if t == "SLOW":
            time.sleep(3)
        out = {"ticker": t, "sec_ticker": s, "status": "ok", "score": 1.0, "n_claims": 1, "n_verified": 1}
        emit("done", t, s, out, False)
        return out

    monkeypatch.setattr(firms, "_one", slow)
    monkeypatch.setattr(firms, "sec_ticker", lambda t, a: t)
    uni = {"FAST": {"asset_class": "equity"}, "SLOW": {"asset_class": "equity"}, "RY": {"asset_class": "equity"}}
    events = []
    t0 = time.time()
    res = firms.analyse({"FAST": .4, "SLOW": .4, "RY": .2}, uni, "2026-11-12",
                        lambda *a: events.append((a[0], a[1], a[3] and a[3]["status"])), {"RY": "no_annual_filing"})
    assert "RY" not in res                            # 40-F filer: skipped, not read for minutes
    assert time.time() - t0 < 2.5
    assert res["FAST"]["status"] == "ok" and res["SLOW"]["status"] == "pending"
    time.sleep(2.2)                                   # the stalled thread finishes late: no second "done"
    assert [e for e in events if e[0] == "done" and e[1] == "SLOW"] == [("done", "SLOW", "pending")]


def test_concurrent_runs_share_one_read(monkeypatch):
    """Two analyses needing the same company while it is being read: one agent call, both get the result,
    and it is saved for the next run."""
    import threading
    from core import storage
    calls, gate = [], threading.Event()

    def read(t, s, as_of, key):
        calls.append(s)
        gate.wait(5)
        out = {"ticker": t, "sec_ticker": s, "status": "ok", "score": 1.0, "n_claims": 1, "n_verified": 1, "channels": []}
        storage.write_json(key, out)
        return out
    monkeypatch.setattr(firms, "_read", read)
    res = {}
    runs = [threading.Thread(target=lambda i=i: res.__setitem__(i, firms._one("CNR.TO" if i else "CNI", "CNI", "2026-11-12",
                                                                               lambda *a: None))) for i in range(2)]
    for r in runs:
        r.start()
    time.sleep(0.3)
    gate.set()
    for r in runs:
        r.join(5)
    assert calls == ["CNI"] and res[0]["status"] == res[1]["status"] == "ok"
    assert (res[0]["ticker"], res[1]["ticker"]) == ("CNI", "CNR.TO")      # each run sees its own ticker
    assert firms._one("CNI", "CNI", "2026-11-12", lambda *a: None)["status"] == "ok" and calls == ["CNI"]   # saved
