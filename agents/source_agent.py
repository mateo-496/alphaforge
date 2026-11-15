"""Source agent: official institutions to consult for a country (central bank, finance ministry, statistics office,
IMF and World Bank country pages). No LLM and no invented URLs: a curated list of real addresses, each fetched to
check it is reachable (result cached 7 days). Unreachable addresses are left out of the report.

    python -m agents.source_agent CAN
"""
import sys
import time

import httpx

from core.storage import cached

EURO = {"AUT", "BEL", "HRV", "CYP", "EST", "FIN", "FRA", "DEU", "GRC", "IRL", "ITA", "LVA", "LTU", "LUX", "MLT",
        "NLD", "PRT", "SVK", "SVN", "ESP"}
_ECB = ("European Central Bank", "https://www.ecb.europa.eu/home/html/index.en.html", "central_bank")
REGISTRY: dict[str, list[tuple[str, str, str]]] = {
    "USA": [("Federal Reserve Board", "https://www.federalreserve.gov/", "central_bank"),
            ("U.S. Treasury Fiscal Data", "https://fiscaldata.treasury.gov/", "finance_ministry"),
            ("Federal Register", "https://www.federalregister.gov/", "regulator")],
    "CAN": [("Bank of Canada", "https://www.bankofcanada.ca/", "central_bank"),
            ("Statistics Canada", "https://www.statcan.gc.ca/en/start", "statistics_office")],
    "CHN": [("People's Bank of China", "https://www.pbc.gov.cn/english/130437/index.html", "central_bank"),
            ("Ministry of Finance of the PRC", "https://www.mof.gov.cn/en/abus/os/rd/", "finance_ministry")],
    "JPN": [("Bank of Japan", "https://www.boj.or.jp/en/", "central_bank"),
            ("Ministry of Finance Japan", "https://www.mof.go.jp/english/index.htm", "finance_ministry")],
    "GBR": [("Bank of England", "https://www.bankofengland.co.uk/", "central_bank"),
            ("Office for National Statistics", "https://www.ons.gov.uk/", "statistics_office")],
    "IND": [("Reserve Bank of India", "https://www.rbi.org.in/", "central_bank"),
            ("Ministry of Statistics (MoSPI)", "https://www.mospi.gov.in/", "statistics_office")],
    "TWN": [("Central Bank of the Republic of China (Taiwan)", "https://www.cbc.gov.tw/en/", "central_bank"),
            ("DGBAS National Statistics", "https://eng.stat.gov.tw/", "statistics_office")],
    "KOR": [("Bank of Korea", "https://www.bok.or.kr/eng/main/main.do", "central_bank"),
            ("Statistics Korea", "https://kostat.go.kr/anse/", "statistics_office")],
    "DEU": [("Deutsche Bundesbank", "https://www.bundesbank.de/en", "central_bank"),
            ("Destatis", "https://www.destatis.de/EN/Home/_node.html", "statistics_office")],
    "FRA": [("Banque de France", "https://www.banque-france.fr/en", "central_bank"),
            ("INSEE", "https://www.insee.fr/en/accueil", "statistics_office")],
    "MEX": [("Banco de México", "https://www.banxico.org.mx/indexEn.html", "central_bank"),
            ("INEGI", "https://en.www.inegi.org.mx/", "statistics_office")],
    "BRA": [("Banco Central do Brasil", "https://www.bcb.gov.br/en", "central_bank"),
            ("IBGE", "https://www.ibge.gov.br/en/", "statistics_office")],
    "AUS": [("Reserve Bank of Australia", "https://www.rba.gov.au/", "central_bank"),
            ("Australian Bureau of Statistics", "https://www.abs.gov.au/", "statistics_office")],
    "HKG": [("Hong Kong Monetary Authority", "https://www.hkma.gov.hk/eng/", "central_bank"),
            ("Census and Statistics Department", "https://www.censtatd.gov.hk/en/", "statistics_office")],
    "RUS": [("Bank of Russia", "https://cbr.ru/eng/", "central_bank"),
            ("Ministry of Finance of the Russian Federation", "https://minfin.gov.ru/en/", "finance_ministry")],
}
UA = {"User-Agent": "Mozilla/5.0 (AlphaForge datathon research prototype)"}


def candidates(iso3: str) -> list[dict]:
    rows = list(REGISTRY.get(iso3, [])) + ([_ECB] if iso3 in EURO else [])
    rows += [("IMF country page", f"https://www.imf.org/en/Countries/{iso3}", "multilateral"),
             ("World Bank country data", f"https://data.worldbank.org/country/{iso3}", "multilateral")]
    return [{"name": n, "url": u, "type": t} for n, u, t in rows]


BOT_WALL = {401, 403, 405, 406, 429}   # the site answered but refuses scripts: it exists


def _check(url: str) -> dict:
    """Three attempts with backoff; a bot wall counts as reachable (the page exists for a reader)."""
    last = {"live": False, "status": None}
    for attempt in range(3):
        try:
            r = httpx.get(url, headers=UA, timeout=httpx.Timeout(12, connect=6), follow_redirects=True)
            if r.status_code < 400 or r.status_code in BOT_WALL:
                return {"live": True, "status": r.status_code, "final_url": str(r.url)}
            last = {"live": False, "status": r.status_code}
            if r.status_code < 500:
                break
        except Exception as e:
            last = {"live": False, "status": None, "error": type(e).__name__}
        time.sleep(1 + attempt)
    return last


def official_sources(iso3: str) -> list[dict]:
    """Official sources for a country: [{name, url, type, checked}]. A failed check is cached 6 h, a pass 7 days.
    If none answers, the IMF and World Bank country pages are kept anyway (stable official addresses), unchecked."""
    out = []
    for c in candidates(iso3):
        key = {"url": c["url"], "v": 2}
        chk = cached("source-check", key, lambda: _check(c["url"]), hours=24 * 7)
        if not chk["live"]:
            chk = cached("source-check-retry", {**key, "slot": int(time.time() // 21600)}, lambda: _check(c["url"]),
                         hours=6)
        if chk["live"]:
            out.append({**c, "url": chk.get("final_url") or c["url"], "checked": True})
    if not out:
        out = [{**c, "checked": False} for c in candidates(iso3) if c["type"] == "multilateral"]
    return out


if __name__ == "__main__":
    for s in official_sources(sys.argv[1].upper() if len(sys.argv) > 1 else "CAN"):
        print(f"{s['type']:18} {s['name']:45} {s['url']}")
