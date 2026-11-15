"""Inputs for the scenario agent, fetched by code (no agent browsing):
  * 4 ranked risk reports, main text cut to MAX_CHARS each
  * the Caldara–Iacoviello GPR index: global + country z-scores, compact table
Both are cached per ISO week in storage (scenarios/inputs/<week>/...), so regenerating in the same week
does not download again, and the exact text the model saw is kept with every query.
"""
import io
import re
import time
from datetime import date, datetime, timezone

import httpx

from core import storage

UA = {"User-Agent": "Mozilla/5.0 (AlphaForge datathon research prototype)"}
MAX_CHARS = 7_000
TIMEOUT = 15

SOURCES = {
    "eurasia_top_risks": {"name": "Eurasia Group — Top Risks 2026",
                          "url": "https://www.eurasiagroup.net/issues/Top-Risks-2026"},
    "blackrock_grd": {"name": "BlackRock — Geopolitical Risk Dashboard",
                      "url": "https://www.blackrock.com/sg/en/insights/geopolitical-risk-dashboard"},
    "cfr_pps": {"name": "CFR — Preventive Priorities Survey",
                "url": "https://www.cfr.org/programs/center-preventive-action"},
    "atlantic_foresight": {"name": "Atlantic Council — Global Foresight",
                           "url": "https://www.atlanticcouncil.org/content-series/atlantic-council-strategy-paper-series/welcome-to-2036/"},
}
GPR_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls"

RISK_WORDS = re.compile(r"risk|war|conflict|tariff|sanction|election|crisis|tension|escalat|china|russia|iran|taiwan|"
                        r"trade|security|attack|nuclear|coup|military|ceasefire|oil|energy", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _main_text(html: str) -> str:
    """Main text, keeping the paragraphs that talk about risks first so the cut keeps the useful part."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "nav", "footer", "header", "form", "noscript", "svg", "aside", "button"]):
        t.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    paras = [re.sub(r"\s+", " ", p.get_text(" ")).strip() for p in root.find_all(["h1", "h2", "h3", "p", "li"])]
    paras = [p for p in paras if len(p) > 40]
    if not paras:
        return re.sub(r"\s+", " ", root.get_text(" ")).strip()[:MAX_CHARS]
    seen, out = set(), []
    for p in paras:  # keep page order, drop duplicates and paragraphs with no risk vocabulary
        if p not in seen and RISK_WORDS.search(p):
            seen.add(p)
            out.append(p)
    text = "\n".join(out)
    return text[:MAX_CHARS]


def _fetch_one(week: str, sid: str, s: dict, emit) -> dict:
    key = f"scenarios/inputs/{week}/{sid}.json"
    cached = storage.read_json(key)
    if cached and cached.get("ok"):
        emit("source", "done", sid, s["name"], "cached this week")
        return cached
    emit("source", "start", sid, s["name"], s["url"])
    t0 = time.time()
    try:
        r = httpx.get(s["url"], headers=UA, timeout=TIMEOUT, follow_redirects=True)
        r.raise_for_status()
        text = _main_text(r.text)
        ok = len(text) > 300
        rec = {"id": sid, "name": s["name"], "url": str(r.url), "ok": ok, "text": text, "chars": len(text),
               "error": None if ok else "page has almost no text (JavaScript-rendered?)",
               "retrieved_at": _now(), "ms": int((time.time() - t0) * 1000)}
    except Exception as e:
        rec = {"id": sid, "name": s["name"], "url": s["url"], "ok": False, "text": "", "chars": 0,
               "error": f"{type(e).__name__}: {str(e)[:160]}", "retrieved_at": _now()}
    storage.write_json(key, rec)
    emit("source", "done", sid, s["name"], f"{rec['chars']:,} characters" if rec["ok"] else "unavailable")
    return rec


def fetch_sources(week: str, on_event=None) -> list[dict]:
    """[{id, name, url, ok, text, chars, error, retrieved_at}] — fetched in parallel, cached per week."""
    from concurrent.futures import ThreadPoolExecutor
    emit = on_event or (lambda *a, **k: None)
    with ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        futures = [pool.submit(_fetch_one, week, sid, s, emit) for sid, s in SOURCES.items()]
        return [f.result() for f in futures]


def gpr_snapshot(week: str, on_event=None, top: int = 15) -> dict | None:
    """Global GPR + the `top` countries with the highest z-score vs. their own history (shared table, tools/gpr.py)."""
    from tools import gpr
    emit = on_event or (lambda *a, **k: None)
    emit("source", "start", "gpr", "Caldara–Iacoviello GPR index", GPR_URL)
    try:
        tbl = gpr.table(week)
        today = date.today().isoformat()
        rows = [x for x in (gpr.at(tbl, c, today) for c in gpr.covered(tbl)) if x]
        rows.sort(key=lambda c: -c["z"])
        g = gpr.at(tbl, "GLOBAL", today)
        snap = {"source": gpr.CITATION, "url": GPR_URL, "retrieved_at": tbl["retrieved_at"],
                "global": {"last_month": g["month"], "last": g["level"], "z": g["z"]} if g else None,
                "countries": [{"iso3": c["iso3"], "last_month": c["month"], "last": c["level"], "z": c["z"]} for c in rows[:top]]}
    except Exception as e:
        emit("source", "done", "gpr", "Caldara–Iacoviello GPR index", "unavailable")
        return {"error": f"{type(e).__name__}: {str(e)[:160]}"}
    emit("source", "done", "gpr", "Caldara–Iacoviello GPR index", f"top {len(snap['countries'])} countries")
    return snap


def quote_is_verified(text: str, quote: str) -> bool:
    def norm(s: str) -> str:
        s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("—", "-").replace("–", "-")
        return re.sub(r"\s+", " ", s).strip().lower()
    q = norm(quote)
    return bool(q) and len(q) >= 15 and q in norm(text)
