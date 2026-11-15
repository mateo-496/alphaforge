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
