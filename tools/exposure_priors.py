"""Priors for a company's country revenue split, used when its filing gives none (or to fill what it leaves out).

  sector prior     peers in the same industry (else GICS sector) that report a split: their average domestic share
                   h_s and average foreign mix pi_sc, from the peer library below
  home-bias prior  w_ic = h_s 1[c = home_i] + (1 - h_s) pi_sc, with pi_sc = world GDP weights when no peers report
  returns-based    constrained regression of the stock's weekly returns on country index ETFs, world market
                   controlled for; weights >= 0 summing to 1; only prices up to as_of (no look-ahead)

Peer library: every split read from a filing is stored (core.storage exposure-library/), with its filing date, so a
prior for an analysis date only uses peers filed by then. It grows with every analysis; `python -m
agents.exposure_agent --warm` fills it from the starter universe."""
from datetime import date

import numpy as np

from core import storage
from core.storage import cached
from tools import market_data, worldbank

MIN_PEERS = 3
# Domestic share used only until the library holds MIN_PEERS companies with a reported home share (an assumption,
# shown as such in the report): large listed companies typically earn most, not all, of their revenue at home.
H_DEFAULT = 0.6
LIB = "exposure-library"


def industry(ticker: str) -> str | None:
    """Yahoo industry (close to a GICS sub-industry), cached 30 days; None if unavailable."""
    def fetch():
        import yfinance as yf
        return {"industry": (yf.Ticker(ticker).info or {}).get("industry")}
    try:
        return cached("yahoo-industry", {"ticker": ticker}, fetch, hours=24 * 30)["industry"]
    except Exception:
        return None


# ---------- peer library ----------
def record(ticker: str, home: str | None, shares: dict[str, float], filing_date: str, ind: str | None,
           sector: str | None) -> None:
    """Store a reported split (explicit countries only, ISO3) for use as a peer."""
    if shares:
        storage.write_json(f"{LIB}/{ticker}.json", {"ticker": ticker, "home": home, "shares": shares,
                                                   "filing_date": filing_date, "industry": ind, "sector": sector})


def peers(as_of: str, exclude: str) -> list[dict]:
    out = []
    for k in storage.list_keys(f"{LIB}/"):
        p = storage.read_json(k)
        if p and p["ticker"] != exclude and p["filing_date"] <= as_of:
            out.append(p)
    return out


def _stats(group: list[dict]) -> tuple[float | None, dict[str, float] | None, int, int]:
    """(h, pi, peers behind h, peers behind pi). pi averages each peer's foreign mix, normalised."""
    hs = [p["shares"][p["home"]] for p in group if p.get("home") in p["shares"]]
    mixes = []
    for p in group:
        f = {c: v for c, v in p["shares"].items() if c != p.get("home")}
        tot = sum(f.values())
        if tot > 0:
            mixes.append({c: v / tot for c, v in f.items()})
    pi: dict[str, float] = {}
    for m in mixes:
        for c, v in m.items():
            pi[c] = pi.get(c, 0.0) + v / len(mixes)
    return (sum(hs) / len(hs) if hs else None), (pi or None), len(hs), len(mixes)


def sector_stats(as_of: str, exclude: str, ind: str | None, sector: str | None) -> dict:
    """h_s and pi_sc from the closest peer group with at least MIN_PEERS companies; which group was used."""
    lib = peers(as_of, exclude)
    out = {"h": None, "pi": None, "h_from": None, "pi_from": None}
    for name, group in (("industry", [p for p in lib if ind and p.get("industry") == ind]),
                        ("sector", [p for p in lib if sector and p.get("sector") == sector]),
                        ("all peers", lib)):
        h, pi, nh, npi = _stats(group)
        if out["h"] is None and nh >= MIN_PEERS:
            out.update(h=h, h_from=f"{name} ({nh})")
        if out["pi"] is None and npi >= MIN_PEERS and name != "all peers":
            out.update(pi=pi, pi_from=f"{name} ({npi})")
    return out


# ---------- priors ----------
def home_bias(home: str, h: float, pi: dict[str, float]) -> dict[str, float]:
    """w_c = h 1[c = home] + (1 - h) pi_c, with pi renormalised without the home country. Without any foreign mix
    the foreign share stays unattributed ("Other") rather than being guessed."""
    foreign = {c: v for c, v in pi.items() if c != home}
    tot = sum(foreign.values())
    w = {c: (1 - h) * v / tot for c, v in foreign.items()} if tot else {"Other": 1 - h}
    w[home] = w.get(home, 0.0) + h
    return w


def _gdp(as_of: str, top: int = 60) -> dict[str, float]:
    try:
        return worldbank.gdp_weights(as_of, top)
    except Exception:
        return {}


def company_prior(ticker: str, home: str | None, as_of: str, ind: str | None, sector: str | None) -> dict:
    """{"weights", "code" (sector_prior | home_bias), "detail"} for a company with a known home country."""
    st = sector_stats(as_of, ticker, ind, sector)
    pi, pi_from = st["pi"], st["pi_from"]
    if pi is None:
        pi = _gdp(as_of)
        pi_from = "world GDP weights" if pi else "nothing (World Bank unreachable): foreign share left unattributed"
    h, h_from = (st["h"], st["h_from"]) if st["h"] is not None else (H_DEFAULT, "default, too few reporting peers")
    code = "sector_prior" if st["pi"] is not None and st["h"] is not None else "home_bias"
    return {"weights": home_bias(home, h, pi), "code": code,
            "detail": f"home share {h:.0%} ({h_from}); foreign mix from {pi_from}"}


def gdp_over(countries: list[str], as_of: str) -> dict[str, float]:
    """GDP weights restricted to `countries` (equal only if the World Bank has none of them)."""
    g = _gdp(as_of, top=250)
    known = {c: g[c] for c in countries if c in g}
    tot = sum(known.values())
    return {c: v / tot for c, v in known.items()} if tot else {"Other": 1.0}


def within(members: list[str], prior: dict[str, float], as_of: str) -> dict[str, float]:
    """Split one reported region across its member countries by the prior (pi_sc), else by GDP."""
    m = {c: prior.get(c, 0.0) for c in members}
    tot = sum(m.values())
    return {c: v / tot for c, v in m.items() if v > 0} if tot > 0 else gdp_over(members, as_of)


# ---------- returns-based estimate ----------
WORLD = "ACWI"
COUNTRY_ETF = {"USA": "SPY", "CAN": "EWC", "JPN": "EWJ", "GBR": "EWU", "DEU": "EWG", "FRA": "EWQ", "CHE": "EWL",
               "NLD": "EWN", "ITA": "EWI", "ESP": "EWP", "SWE": "EWD", "AUS": "EWA", "CHN": "MCHI", "TWN": "EWT",
               "KOR": "EWY", "IND": "INDA", "BRA": "EWZ", "MEX": "EWW", "ZAF": "EZA", "SAU": "KSA", "IDN": "EIDO",
               "HKG": "EWH", "SGP": "EWS"}
WEEKS = 104
MIN_WEEKS = 52


def _weekly(ticker: str, as_of: str) -> dict[str, float]:
    """Weekly log returns keyed by ISO week, from adjusted closes up to as_of."""
    obs = market_data.get_price_history(ticker, min(as_of, date.today().isoformat()), 7 * WEEKS + 21)["observations"]
    last: dict[str, float] = {}
    for o in obs:   # last close of each ISO week
        y, w, _ = date.fromisoformat(str(o["date"])).isocalendar()
        last[f"{y}-{w:02d}"] = o["value"]
    keys = sorted(last)
    return {k: float(np.log(last[k] / last[p])) for p, k in zip(keys, keys[1:])}


def _simplex(v: np.ndarray) -> np.ndarray:
    """Euclidean projection onto {w >= 0, sum w = 1}."""
    u = np.sort(v)[::-1]
    css = np.cumsum(u) - 1
    k = np.nonzero(u - css / np.arange(1, len(v) + 1) > 0)[0][-1]
    return np.maximum(v - css[k] / (k + 1), 0)


def style_weights(y: np.ndarray, world: np.ndarray, countries: np.ndarray, iters: int = 5000) -> tuple[np.ndarray, float]:
    """min ||y~ - E w||^2, w >= 0, sum w = 1, where y~ and the columns E are y and the country returns with the
    world market (and a constant) regressed out. Returns (w, R^2 of the country part)."""
    X = np.column_stack([np.ones_like(world), world])
    resid = lambda v: v - X @ np.linalg.lstsq(X, v, rcond=None)[0]
    yt = resid(y)
    E = np.column_stack([resid(countries[:, j]) for j in range(countries.shape[1])])
    L = np.linalg.norm(E, 2) ** 2 or 1.0
    w = np.full(E.shape[1], 1 / E.shape[1])
    for _ in range(iters):   # projected gradient descent
        w = _simplex(w - E.T @ (E @ w - yt) / L)
    ss = float(yt @ yt)
    return w, (1 - float(np.sum((yt - E @ w) ** 2)) / ss) if ss else 0.0


def returns_based(ticker: str, as_of: str) -> dict | None:
    """{"weights", "r2", "weeks"} or None when prices are too short or unavailable."""
    try:
        y, wr = _weekly(ticker, as_of), _weekly(WORLD, as_of)
        cr = {c: _weekly(etf, as_of) for c, etf in COUNTRY_ETF.items()}
    except Exception:
        return None
    weeks = sorted(set(y) & set(wr) & set.intersection(*(set(v) for v in cr.values())))[-WEEKS:]
    if len(weeks) < MIN_WEEKS:
        return None
    cs = list(COUNTRY_ETF)
    w, r2 = style_weights(np.array([y[k] for k in weeks]), np.array([wr[k] for k in weeks]),
                          np.array([[cr[c][k] for c in cs] for k in weeks]))
    keep = {c: float(v) for c, v in zip(cs, w) if v >= 0.01}
    tot = sum(keep.values())
    return {"weights": {c: v / tot for c, v in keep.items()}, "r2": round(r2, 3), "weeks": len(weeks)} if tot else None
