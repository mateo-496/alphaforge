"""Caldara–Iacoviello Geopolitical Risk (GPR) index: downloaded once per week, queried per country and date.

Point in time: a query for `as_of` only uses months strictly before as_of's month (the index for a month is
published after the month ends), and the z-score uses history up to that month only.
"""
import io
from datetime import date, datetime, timezone

import httpx

from core import storage

URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls"
CITATION = "Caldara, D. and Iacoviello, M. (2022), Measuring Geopolitical Risk, American Economic Review"
UA = {"User-Agent": "Mozilla/5.0 (AlphaForge datathon research prototype)"}


def _week() -> str:
    y, w, _ = date.today().isocalendar()
    return f"{y}-W{w:02d}"


def table(week: str | None = None) -> dict:
    """{"retrieved_at", "url", "months": [YYYY-MM], "series": {"GLOBAL": [...], "CHN": [...]}} (None = missing)."""
    key = f"gpr/{week or _week()}.json"
    cached = storage.read_json(key)
    if cached:
        return cached
    import pandas as pd
    r = httpx.get(URL, headers=UA, timeout=30, follow_redirects=True)
    r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content))
    df["month"] = pd.to_datetime(df["month"]).dt.strftime("%Y-%m")
    df = df.sort_values("month")
    cols = {"GLOBAL": "GPR", **{c[5:]: c for c in df.columns if c.startswith("GPRC_")}}
    out = {"retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "url": URL,
           "months": df["month"].tolist(),
           "series": {k: [None if pd.isna(v) else round(float(v), 4) for v in df[c]] for k, c in cols.items() if c in df}}
    storage.write_json(key, out)
    return out


def at(tbl: dict, iso3: str, as_of: str) -> dict | None:
    """Level, 12-month mean and z-score vs. the country's own history, for the last full month before as_of."""
    s = tbl["series"].get(iso3)
    if not s:
        return None
    cutoff = as_of[:7]
    pts = [(m, v) for m, v in zip(tbl["months"], s) if m < cutoff and v is not None]
    if len(pts) < 36:
        return None
    vals = [v for _, v in pts]
    mean = sum(vals) / len(vals)
    sd = (sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5
    return {"iso3": iso3, "month": pts[-1][0], "level": vals[-1], "mean_12m": round(sum(vals[-12:]) / 12, 4),
            "z": round((vals[-1] - mean) / sd, 2) if sd else 0.0,
            "pct": round(sum(v <= vals[-1] for v in vals) / len(vals), 3), "since": pts[0][0][:4]}


def covered(tbl: dict) -> list[str]:
    return [k for k in tbl["series"] if k != "GLOBAL"]
