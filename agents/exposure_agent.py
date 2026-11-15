"""Exposure agent: each holding's country revenue split w_ic, from the best source available, tagged by tier.

Fallback chain, best to worst (a reported tier is blended with the prior: w = lambda w_reported + (1 - lambda) w_prior):
  1. xbrl     XBRL geographic table of the latest 10-K / 20-F / 40-F filed on or before as_of     lambda 1.0
  2. text     filing text (geographic note, MD&A), read by the LLM; every share must sit in a
              verbatim quote that states that number                                               lambda 0.8
  3. stale    the company's previous filing when the latest has no split, or a fiscal year
              ending more than ~18 months before as_of                                              lambda 0.6
  4. sector prior, 5. home-bias prior, 6. returns-based estimate    (tools/exposure_priors.py)   lambda 0
Reported regions ("Asia Pacific") and "outside the U.S." lines are split by the prior's mix, not evenly; the share a
filing leaves unattributed follows the prior too. Funds: returns-based for equity ETFs, recorded countries weighted
by GDP for bond ETFs; commodities and crypto have no country.
EDGAR refusals (HTTP 403 / 429) are reported as "blocked", never treated as "no filing".

Cheapest check first, stop at the first that applies (the step is logged and shown per holding):
  xbrl -> cache (exposure-splits/{accession}.json) -> prior:small (weight < 2%) -> prior:domestic (banks, utilities,
  telecoms, REITs, regional insurers: home 90%, rest by the prior) -> carry (same fiscal year already read) ->
  main-document snippets around geographic wording (none: prior:nomatch, no LLM) -> regex shares (accepted when they
  add up to 0.9-1.05) -> llm on the snippets only, within EXPOSURE_TEXT_WAIT_S -> stale XBRL -> prior.

    python -m agents.exposure_agent NVDA --as-of 2026-11-12
    python -m agents.exposure_agent --warm --as-of 2026-11-12     # fill the peer library from the starter universe
"""
import argparse
import json
import logging
import re
from datetime import date

from pydantic import BaseModel, Field

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from core import config, llm, storage
from tools import exposure_priors as P
from tools import filings
from web import universe as U
from web.market import ISO2_TO_3, REGION_LABEL, region_members, sec_ticker

AGENT = "exposure"
log = logging.getLogger(__name__)
DOMESTIC_HOME_LABEL = "90%"
LAMBDA = {"xbrl": 1.0, "text": 0.8, "stale": 0.6}
LABEL = {"xbrl": "SEC XBRL", "text": "filing text", "stale": "last year's filing", "sector_prior": "sector prior",
         "home_bias": "home-bias prior", "returns": "returns-based", "recorded": "recorded countries, GDP-weighted",
         "none": "no country", "domestic": f"domestic-sector prior (home {DOMESTIC_HOME_LABEL})", "carry": "same fiscal year, carried"}
LISTING = {"TSX": "CAN", "NASDAQ": "USA", "NYSE": "USA", "NYSE Arca": "USA", "Cboe BZX": "USA"}
FOREIGN_REGIONS = {"ROW", "INTL"}   # "rest of world", "international": outside the home country
MAX_TEXT = 10_000

SYSTEM_PROMPT = """You read passages of a company's annual filing and extract how its revenue splits by geography.
Return one row per stated share: place is an ISO 3166-1 alpha-3 country code, HOME (the company's home country),
FOREIGN (everything outside the home country), or one of these region codes: """ + ", ".join(REGION_LABEL) + """.
share is the fraction of TOTAL revenue (0-1). quote is copied VERBATIM from the passages and must contain the number
you report (e.g. "approximately 45% of our revenue came from customers outside the United States").
Only shares stated in the passages, for the most recent fiscal year. Return no rows if no share is stated."""


class SplitRow(BaseModel):
    place: str = Field(description="ISO alpha-3, HOME, FOREIGN or a region code")
    share: float = Field(ge=0, le=1)
    quote: str


class DraftSplit(BaseModel):
    rows: list[SplitRow]


def home_country(ticker: str, asset: dict) -> str | None:
    meta = next((a for t, a in U.load()["assets"].items() if (U.normalise_ticker(t) or t) == ticker), {})
    return meta.get("country") or asset.get("country") or LISTING.get(asset.get("market", ""))


# ---------- tier 2: filing text ----------
_NUM = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:%|percent|per cent)", re.I)


def states(quote: str, share: float) -> bool:
    """The quote states this share as a percentage (to half a point)."""
    return any(abs(float(n) - 100 * share) <= 0.5 for n in _NUM.findall(quote))


_TEXT_POOL = ThreadPoolExecutor(max_workers=6, thread_name_prefix="exposure-text")

# ---------- cheap checks before any filing text is read ----------
SMALL_WEIGHT = 0.02          # below this the prior's error barely moves the portfolio score
DOMESTIC_HOME = 0.9          # banks, utilities, telecoms, REITs, regional insurers: assumed home share
DOMESTIC = re.compile(r"^(banks|utilities|telecom|reit|real estate|insurance - (property|life|specialty))", re.I)
SPLITS = "exposure-splits"   # {accession}.json: the split read from that filing's text (a filing never changes)

KEY = re.compile(r"geographic|by region|by country|segment information|revenues? (?:derived|generated)"
                 r"|substantially all (?:of )?(?:our )?(?:revenue|sales)"
                 r"|\d\s?%\s+of\s+(?:our\s+)?(?:total\s+)?(?:net\s+)?(?:revenue|sales)", re.I)
PCT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s?%\s+of\s+(?:our\s+)?(?:total\s+)?(?:net\s+)?(?:revenues?|sales)", re.I)
ALL = re.compile(r"substantially all (?:of )?(?:our )?(?:revenues?|sales)[^.]{0,120}", re.I)
SNIP, MAX_SNIPS, NEAR = 750, 8, 150
_PLACES = [   # longest first: "Europe, Middle East and Africa" before "Europe"
    (r"Europe,? (?:the )?Middle East,? and Africa|EMEA", "REGION:EMEA"), (r"Middle East and Africa", "REGION:MEA"),
    (r"(?:the )?Americas", "REGION:AMERICAS"), (r"North America", "REGION:NORTHAM"),
    (r"Latin America|South America", "REGION:LATAM"), (r"Asia[- ]Pacific|APAC", "REGION:APAC"),
    (r"Greater China", "REGION:GCHINA"), (r"Europe", "REGION:EUROPE"),
    (r"rest of (?:the )?world|other countries", "REGION:ROW"),
    (r"outside (?:of )?(?:the )?[A-Z][\w.]*(?: [A-Z][\w.]*)?|international|overseas|foreign", "FOREIGN"),
    (r"domestic|home market", "HOME"),
    (r"United States|U\.S\.(?:A\.)?|USA", "USA"), (r"Canada", "CAN"), (r"Mexico", "MEX"), (r"Brazil", "BRA"),
    (r"United Kingdom|U\.K\.", "GBR"), (r"Germany", "DEU"), (r"France", "FRA"), (r"Italy", "ITA"), (r"Spain", "ESP"),
    (r"Netherlands", "NLD"), (r"Switzerland", "CHE"), (r"Ireland", "IRL"), (r"Hong Kong", "HKG"),
    (r"(?:mainland )?China|PRC", "CHN"), (r"Taiwan", "TWN"), (r"Japan", "JPN"), (r"(?:South )?Korea", "KOR"),
    (r"India", "IND"), (r"Australia", "AUS"), (r"Singapore", "SGP"), (r"Indonesia", "IDN"), (r"Thailand", "THA"),
    (r"Vietnam", "VNM"), (r"Malaysia", "MYS"), (r"Philippines", "PHL"), (r"Saudi Arabia", "SAU"),
    (r"United Arab Emirates|UAE", "ARE"), (r"Israel", "ISR"), (r"South Africa", "ZAF"), (r"Chile", "CHL"),
    (r"Argentina", "ARG"), (r"Colombia", "COL"), (r"Peru", "PER"), (r"Turkey|T[üu]rkiye", "TUR")]
PLACE = re.compile("|".join(f"(?P<p{i}>\\b(?:{rx})\\b)" for i, (rx, _) in enumerate(_PLACES)))


_PCT_ANY = re.compile(r"\d\s?%")


def _next_pct(s: str, i: int) -> int:
    m = _PCT_ANY.search(s, i)
    return m.start() if m else -1


def _prev_pct(s: str, i: int) -> int:
    ends = [m.end() for m in _PCT_ANY.finditer(s, 0, i)]
    return ends[-1] if ends else -1


def _place_at(m: re.Match) -> str:
    return _PLACES[int(m.lastgroup[1:])][1]


def domestic(ind: str | None, sector: str | None) -> bool:
    return bool(DOMESTIC.match(ind or "")) or (sector or "") in ("Utilities", "Real Estate")


def snippets(text: str) -> list[str]:
    """~1,500-character windows around geographic / revenue-share wording, overlapping windows merged."""
    spans: list[list[int]] = []
    for m in KEY.finditer(text):
        a, b = max(0, m.start() - SNIP), m.end() + SNIP
        if spans and a <= spans[-1][1]:
            spans[-1][1] = b
        else:
            spans.append([a, b])
        if len(spans) > MAX_SNIPS:
            break
    return [re.sub(r"\s+", " ", text[a:b]) for a, b in spans[:MAX_SNIPS]]


def regex_split(snips: list[str], home: str | None) -> tuple[dict[str, float], list[dict]]:
    """Shares stated as "N% of (our) (total) (net) revenue/sales" next to a place name, first statement per place
    (filings repeat prior years after the current one); "substantially all of our revenue ... <country>" -> 1.0."""
    split, rows = {}, []
    for sn in snips:
        for m in ALL.finditer(sn):
            p = next((_place_at(x) for x in PLACE.finditer(m.group(0))), None)
            if p and not p.startswith("REGION:") and p != "FOREIGN":
                p = home if p == "HOME" else p
                if p:
                    return {p: 1.0}, [{"place": p, "share": 1.0, "quote": m.group(0).strip()}]
        for m in PCT.finditer(sn):
            # "N% of revenue from <place>" first, else "<place> accounted for N% of revenue"; never across another
            # percentage or a sentence end
            after_end = min([x for x in (sn.find(".", m.end()), _next_pct(sn, m.end())) if x >= 0] or [len(sn)])
            after = PLACE.search(sn, m.end(), min(after_end, m.end() + NEAR // 2))
            before_start = max([sn.rfind(". ", 0, m.start()), _prev_pct(sn, m.start()), m.start() - NEAR])
            before = [x for x in PLACE.finditer(sn, max(0, before_start), m.start())]
            x = after or (before[-1] if before else None)
            if not x:
                continue
            p = _place_at(x)
            p = home if p == home else p
            if p not in split:
                split[p] = float(m.group(1)) / 100
                rows.append({"place": p, "share": split[p], "quote": sn[max(0, m.start() - 80):m.end() + 80].strip()})
    if home and home in split and "HOME" not in split:
        split["HOME"] = split.pop(home)
    if set(split) == {"FOREIGN"}:
        split["HOME"] = 1 - split["FOREIGN"]
    elif set(split) == {"HOME"}:
        split["FOREIGN"] = 1 - split["HOME"]
    return split, rows


def main_text(sec_t: str, as_of: str) -> str:
    """Main document only (no exhibits), as plain text."""
    f = filings._annual_filing(sec_t, as_of)
    try:
        t = f.text()
        if t:
            return t
    except Exception:
        pass
    return re.sub(r"<[^>]+>", " ", f.html() or "")


def llm_split(snips: list[str], sec_t: str) -> tuple[dict[str, float], list[dict]]:
    text = "\n...\n".join(snips)[:MAX_TEXT]
    draft = llm.ask(AGENT, SYSTEM_PROMPT, f"Company: {sec_t}\n\n{text}", DraftSplit, max_tokens=1500)
    regions, countries = {k.upper() for k in REGION_LABEL}, set(ISO2_TO_3.values())
    rows = [r for r in draft.rows if filings.quote_in(r.quote, text) and states(r.quote, r.share)
            and r.place.upper() in regions | countries | {"HOME", "FOREIGN"}]
    split: dict[str, float] = {}
    for r in rows:
        k = r.place.upper()
        k = f"REGION:{k}" if k in regions else k
        split[k] = split.get(k, 0.0) + r.share
    if set(split) == {"FOREIGN"}:          # "X% of revenue from outside the U.S." also states the home share
        split["HOME"] = 1 - split["FOREIGN"]
    elif set(split) == {"HOME"}:
        split["FOREIGN"] = 1 - split["HOME"]
    if sum(split.values()) > 1.05:
        return {}, []
    return split, [{"place": r.place, "share": r.share, "quote": r.quote} for r in rows]


def text_split(sec_t: str, as_of: str, home: str | None = None) -> tuple[dict[str, float], list[dict], str]:
    """(split, quote rows, step): snippets of the main document; regex first, the LLM only when the regex shares
    do not add up to 0.9-1.05. No snippet -> no LLM call."""
    snips = snippets(main_text(sec_t, as_of))
    if not snips:
        return {}, [], "prior:nomatch"
    split, rows = regex_split(snips, home)
    if split and 0.9 <= sum(split.values()) <= 1.05:
        return split, rows, "regex"
    split, rows = llm_split(snips, sec_t)
    return split, rows, "llm" if split else "prior:llm-empty"


# ---------- combining ----------
def resolve(reported: dict[str, float], home: str | None, prior: dict[str, float], as_of: str) -> dict[str, float]:
    """Reported places -> countries. Regions and 'foreign' lines are split by the prior; the unattributed rest too."""
    explicit = {c: v for c, v in reported.items() if not c.startswith("REGION:") and c not in ("HOME", "FOREIGN")}
    if "HOME" in reported and home:
        explicit[home] = explicit.get(home, 0.0) + reported["HOME"]
    out = dict(explicit)

    def spread(share: float, over: dict[str, float]):
        tot = sum(over.values())
        if tot <= 0:
            out["Other"] = out.get("Other", 0.0) + share
            return
        for c, v in over.items():
            out[c] = out.get(c, 0.0) + share * v / tot
    rest = {c: v for c, v in prior.items() if c not in explicit and c != "Other"}
    for k, share in reported.items():
        code = k.split(":", 1)[1] if k.startswith("REGION:") else k
        if k == "FOREIGN" or code in FOREIGN_REGIONS:
            spread(share, {c: v for c, v in rest.items() if c != home})
        elif k.startswith("REGION:"):
            members = [c for c in region_members(k) if c not in explicit] or list(region_members(k))
            spread(share, P.within(members, prior, as_of))
    unattributed = max(0.0, 1.0 - sum(reported.values()))
    if unattributed > 1e-6:   # outside every place the filing names
        covered = {m for k in reported if k.startswith("REGION:") for m in region_members(k)}
        spread(unattributed, {c: v for c, v in rest.items() if c not in covered})
    return out


def blend(lam: float, reported: dict[str, float], prior: dict[str, float]) -> dict[str, float]:
    keys = set(reported) | set(prior)
    w = {c: lam * reported.get(c, 0.0) + (1 - lam) * prior.get(c, 0.0) for c in keys}
    tot = sum(w.values())
    return {c: round(v / tot, 6) for c, v in sorted(w.items(), key=lambda kv: -kv[1]) if v / tot >= 1e-4}


def prior_for(ticker: str, asset: dict, home: str | None, as_of: str, ind: str | None) -> dict:
    cls = asset.get("asset_class")
    if cls in ("crypto", "etf_commodity"):
        return {"weights": {"Other": 1.0}, "code": "none", "detail": "no issuer country"}
    if cls == "etf_equity" or (cls == "equity" and not home):
        rb = P.returns_based(ticker, as_of)
        if rb:
            return {"weights": rb["weights"], "code": "returns",
                    "detail": f"weekly returns on country ETFs, world market controlled, {rb['weeks']} weeks, R² {rb['r2']:.2f}"}
    if cls in ("etf_equity", "etf_bond"):
        meta = next((a for t, a in U.load()["assets"].items() if (U.normalise_ticker(t) or t) == ticker), {})
        recorded = meta.get("primary_countries") or asset.get("primary_countries") or ([home] if home else [])
        if recorded:
            return {"weights": P.gdp_over(recorded, as_of), "code": "recorded",
                    "detail": f"fund's recorded countries ({', '.join(recorded)}), weighted by GDP"}
        return {"weights": {"Other": 1.0}, "code": "none", "detail": "no country information"}
    if not home:
        return {"weights": {"Other": 1.0}, "code": "none", "detail": "no home country and no price history"}
    return P.company_prior(ticker, home, as_of, ind, asset.get("sector") or None)


def _cached_split(acc: str | None) -> dict | None:
    try:
        return storage.read_json(f"{SPLITS}/{acc}.json") if acc else None
    except Exception:
        return None


def _same_year(ticker: str, f: dict) -> dict | None:
    """A split already read for this company's fiscal year from another filing (amendment, re-filed form)."""
    try:
        idx = storage.read_json(f"{SPLITS}/by-ticker/{ticker}.json") or {}
    except Exception:
        return None
    return next((e for acc, e in idx.items() if acc != f.get("accession")
                 and (e.get("report_date") or "")[:4] == (f.get("report_date") or "")[:4]), None)


def _save_split(ticker: str, f: dict, entry: dict) -> None:
    try:
        storage.write_json(f"{SPLITS}/{f['accession']}.json", entry)
        idx = storage.read_json(f"{SPLITS}/by-ticker/{ticker}.json") or {}
        storage.write_json(f"{SPLITS}/by-ticker/{ticker}.json", {**idx, f["accession"]: entry})
    except Exception:
        pass


def reported_split(ticker: str, asset: dict, h: dict, as_of: str, weight: float | None, home: str | None,
                   ind: str | None) -> tuple[dict, str | None, list, str]:
    """Cheapest check first, stop at the first that applies: (split, tier code or None, quotes, step).
    step: cache, xbrl, prior:small, prior:domestic, carry, regex, llm, prior:nomatch, prior:timeout, stale, prior."""
    f = h.get("filing") or {}
    acc = f.get("accession")
    if h.get("exposures") and not h.get("stale"):
        return dict(h["exposures"]), "xbrl", [], "xbrl"
    if (c := _cached_split(acc)) is not None:
        if c.get("split"):
            return c["split"], c["code"], c.get("quotes", []), "cache"
        return ({}, None, [], "cache") if not h.get("exposures") else (dict(h["exposures"]), "stale", [], "cache+stale")
    if weight is not None and weight < SMALL_WEIGHT:
        return {}, None, [], "prior:small"
    if asset.get("asset_class") == "equity" and home and domestic(ind, asset.get("sector")):
        return {}, None, [], "prior:domestic"
    if f and (c := _same_year(ticker, f)):
        return c["split"], c["code"], c.get("quotes", []), "carry"
    reported, quotes, step = {}, [], "prior"
    if f and h.get("sec_ticker") and asset.get("asset_class") == "equity":
        fut = _TEXT_POOL.submit(text_split, h["sec_ticker"], as_of, home)
        try:   # bounded: a slow filing download or LLM call falls through to the next tier instead of hanging
            reported, quotes, step = fut.result(timeout=config.EXPOSURE_TEXT_WAIT_S)
        except FuturesTimeout:
            step = "prior:timeout"
        except Exception as e:
            step = f"prior:error ({type(e).__name__})"
        if acc and step in ("regex", "llm", "prior:nomatch", "prior:llm-empty"):   # deterministic outcomes only
            old = (date.fromisoformat(as_of) - date.fromisoformat(f["report_date"])).days > 550
            _save_split(ticker, f, {"split": reported, "code": ("stale" if old else "text") if reported else None,
                                    "quotes": quotes, "step": step, "report_date": f.get("report_date")})
    if reported:
        old = (date.fromisoformat(as_of) - date.fromisoformat(f["report_date"])).days > 550
        return reported, "stale" if old else "text", quotes, step
    if h.get("exposures"):
        return dict(h["exposures"]), "stale", [], "stale"
    return {}, None, [], step


def split(ticker: str, asset: dict, h: dict, as_of: str, weight: float | None = None) -> dict:
    """Asset report for the pipeline: {country_weights, tier{code, label, lambda, prior, detail, step}, estimated,
    method, source, quotes}. `h` is web/market.fetch_holding's output (XBRL tiers already read); `weight` is the
    holding's portfolio weight (small holdings keep the prior)."""
    home = home_country(ticker, asset)
    ind = P.industry(ticker) if asset.get("asset_class") == "equity" else None
    prior = prior_for(ticker, asset, home, as_of, ind)
    f = h.get("filing") or {}
    reported, code, quotes, step = reported_split(ticker, asset, h, as_of, weight, home, ind)
    source = h.get("exposure_source")
    if code in ("text", "stale") and quotes and f:
        source = {"url": f["base"], "locator": f"{f['form']} filed {f['filing_date']}, text", "retrieved_at": ""}
    if step == "prior:domestic":
        rest = {c: v for c, v in prior["weights"].items() if c != home}
        tot = sum(rest.values())
        prior = {**prior, "code": "domestic", "detail": f"{ind or asset.get('sector')}: home {DOMESTIC_HOME:.0%}",
                 "weights": {home: DOMESTIC_HOME, **{c: (1 - DOMESTIC_HOME) * v / tot for c, v in rest.items()}}
                 if tot else {home: 1.0}}
    timed_out = step == "prior:timeout"
    lam = LAMBDA.get(code, 0.0)
    if reported and home:   # a reported split joins the peer library (explicit countries only)
        shares = {c: v for c, v in reported.items() if c in set(ISO2_TO_3.values())}
        if "HOME" in reported:
            shares[home] = shares.get(home, 0.0) + reported["HOME"]
        P.record(ticker, home, shares, f.get("filing_date", as_of), ind, asset.get("sector") or None)
    weights = blend(lam, resolve(reported, home, prior["weights"], as_of), prior["weights"]) if reported \
        else blend(0.0, {}, prior["weights"])
    tier = {"code": code or prior["code"], "lambda": lam, "prior": prior["code"], "detail": prior["detail"], "step": step,
            "label": (f"{LABEL[code]} (λ {lam:g}) + {LABEL[prior['code']]}" if code and lam < 1 else
                      LABEL[code] if code else LABEL[prior["code"]])}
    why = {"blocked": f"SEC refused the request (HTTP {h.get('http_status')})", "error": "SEC lookup failed",
           "no_sec_ticker": "not an SEC filer", "no_annual_filing": "no annual filing with the SEC"}.get(h.get("exposure_status"))
    if timed_out and not code:
        why = f"filing text not read within {config.EXPOSURE_TEXT_WAIT_S}s"
    log.info("exposure %s: stopped at %s -> %s", ticker, step, tier["label"])
    return {"ticker": ticker, "country_weights": weights, "tier": tier, "estimated": lam < 1, "step": step,
            "status": h.get("exposure_status"),
            "method": tier["label"] + (f" — {why}" if why and not code else "") + f" · prior: {prior['detail']}",
            "source": {"name": f"{ticker} SEC annual filing ({(source or {}).get('locator', '')})",
                       "url": (source or {}).get("url", ""), "retrieved": (source or {}).get("retrieved_at", "")}
                      if source else None,
            "quotes": quotes, "http_status": h.get("http_status")}


if __name__ == "__main__":
    from web import market
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker", nargs="?")
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--warm", action="store_true", help="read the XBRL split of every starter equity into the peer library")
    a = ap.parse_args()
    uni = U.universe()
    tickers = [t for t, x in uni.items() if x.get("starter") and x["asset_class"] == "equity"] if a.warm else [a.ticker]
    for t in tickers:
        rep = split(t, uni[t], market.fetch_holding(t, uni[t], a.as_of), a.as_of)
        print(t, rep["tier"]["label"], json.dumps(dict(list(rep["country_weights"].items())[:6])))
