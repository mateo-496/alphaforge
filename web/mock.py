"""MOCK DATA. Plausible but invented numbers so the web flow can be built before the agents exist.
Replace each block with the real agent/tool output of the same shape."""

# ---- Asset layer (filings agent): country weights of revenue/production, sum to 1 incl. 'Other' ----
EXPOSURE = {
    "RY.TO":  {"CAN": .62, "USA": .24, "Other": .14},
    "TD.TO":  {"CAN": .58, "USA": .38, "Other": .04},
    "MFC.TO": {"CAN": .22, "USA": .30, "JPN": .10, "CHN": .08, "SGP": .08, "Other": .22},
    "ENB.TO": {"CAN": .55, "USA": .43, "Other": .02},
    "CNQ.TO": {"CAN": .90, "USA": .06, "GBR": .04},
    "CNR.TO": {"CAN": .70, "USA": .28, "MEX": .02},
    "FTS.TO": {"CAN": .35, "USA": .62, "Other": .03},
    "ATD.TO": {"USA": .70, "CAN": .16, "Other": .14},
    "SHOP.TO": {"USA": .68, "CAN": .06, "GBR": .07, "Other": .19},
    "CSU.TO": {"CAN": .20, "USA": .40, "GBR": .12, "NLD": .08, "Other": .20},
    "AAPL":   {"USA": .42, "CHN": .27, "TWN": .06, "IND": .05, "JPN": .07, "Other": .13},
    "MSFT":   {"USA": .51, "IRL": .10, "GBR": .06, "DEU": .05, "JPN": .04, "Other": .24},
    "NVDA":   {"USA": .44, "TWN": .24, "CHN": .13, "KOR": .04, "SGP": .03, "Other": .12},
    "GOOGL":  {"USA": .49, "GBR": .06, "JPN": .05, "DEU": .05, "IND": .03, "Other": .32},
    "AMZN":   {"USA": .61, "DEU": .09, "GBR": .07, "JPN": .05, "CHN": .04, "Other": .14},
    "TSLA":   {"USA": .47, "CHN": .22, "DEU": .08, "Other": .23},
    "JPM":    {"USA": .78, "GBR": .08, "Other": .14},
    "JNJ":    {"USA": .52, "DEU": .06, "JPN": .05, "CHN": .04, "Other": .33},
    "PG":     {"USA": .47, "CHN": .08, "GBR": .05, "DEU": .05, "MEX": .04, "Other": .31},
    "XOM":    {"USA": .38, "CAN": .08, "SAU": .05, "QAT": .05, "GBR": .04, "Other": .40},
    # ETFs: look-through of holdings, mock
    "XIU.TO": {"CAN": .78, "USA": .18, "Other": .04},
    "SPY":    {"USA": .60, "CHN": .06, "TWN": .03, "JPN": .03, "GBR": .03, "DEU": .03, "Other": .22},
    "QQQ":    {"USA": .55, "CHN": .10, "TWN": .07, "KOR": .02, "Other": .26},
    "ESGV":   {"USA": .62, "CHN": .05, "TWN": .03, "Other": .30},
    "XBB.TO": {"CAN": 1.0},
    "ZST.TO": {"CAN": 1.0},
    "AGG":    {"USA": 1.0},
    "TLT":    {"USA": 1.0},
    "GLD":    {"Other": 1.0},
    "BTC-USD": {"Other": 1.0},
    "ETH-USD": {"Other": 1.0},
}

def exposure(ticker: str, asset: dict) -> dict[str, float]:
    """Country weights. Starter assets: table above. Sample assets: derived from home / operating /
    look-through countries in examples/portfolios.json (heuristic split, placeholder for the filings agent)."""
    if ticker in EXPOSURE:
        return EXPOSURE[ticker]
    if asset.get("asset_class") == "crypto":
        return {"Other": 1.0}
    look = asset.get("primary_countries") or []
    if look:
        w = 0.85 / len(look)
        return {**{c: round(w, 4) for c in look}, "Other": 0.15}
    home, ops = asset.get("country"), [c for c in asset.get("ops") or [] if c != asset.get("country")]
    if ops:
        out = {home: 0.3} if home else {}
        for c in ops:
            out[c] = round(out.get(c, 0) + 0.6 / len(ops), 4)
        return {**out, "Other": 0.1}
    return {home: 0.7, "Other": 0.3} if home else {"Other": 1.0}


# Firm-specific geopolitical claim score (0-5) from risk-factor text, mock
FIRM_SCORE = {"NVDA": 4.5, "AAPL": 3.5, "TSLA": 3.5, "XOM": 3.0, "CNQ.TO": 2.5, "ENB.TO": 2.5,
              "AMZN": 2.0, "MSFT": 2.0, "GOOGL": 2.0, "SHOP.TO": 1.5, "BTC-USD": 3.0, "ETH-USD": 3.0}

# ---- Country layer (geopolitical agent): R_c 0-100 and one driver line, mock ----
COUNTRY = {
    "USA": (38, "Tariff policy volatility, export-control escalation"),
    "CAN": (32, "US trade measures on steel, aluminium and energy"),
    "CHN": (72, "Export controls, Taiwan tension, capital controls"),
    "TWN": (68, "Cross-strait military pressure"),
    "MEX": (44, "USMCA review, US tariff threats"),
    "GBR": (28, "Low; post-Brexit trade frictions"),
    "DEU": (30, "Energy costs, EU–China trade measures"),
    "JPN": (30, "Regional security, yen volatility"),
    "KOR": (47, "North Korea, chip export rules"),
    "IND": (42, "Border tensions, regulatory shifts"),
    "SAU": (55, "Gulf security, OPEC+ policy"),
    "QAT": (48, "Gulf security, LNG shipping routes"),
    "IRL": (22, "Low; EU tax policy"),
    "NLD": (27, "Semiconductor equipment export rules"),
    "SGP": (24, "Low; transshipment scrutiny"),
    "HKG": (58, "US sanctions exposure, ADR delisting risk"), "IND": (42, "Border tensions, US tariffs"),
    "KOR": (47, "North Korea, chip export rules"), "PHL": (45, "South China Sea incidents"),
    "IDN": (38, "Resource nationalism, export bans"), "THA": (36, "Political instability"),
    "MYS": (30, "Transshipment scrutiny"), "VNM": (40, "US tariff exposure as China substitute"),
    "AUS": (22, "China trade coercion"), "BRA": (45, "Fiscal stress, election cycle"),
    "ARG": (62, "FX controls, debt restructuring"), "CHL": (35, "Lithium nationalisation"),
    "PER": (48, "Mining protests, political turnover"), "COL": (50, "Fiscal stress, security"),
    "URY": (20, "Low"), "PAN": (40, "Canal drought, mining ban"), "DOM": (30, "Low; tax disputes"),
    "FRA": (32, "Fiscal and political fragmentation"), "CHE": (15, "Low"), "DNK": (25, "Greenland dispute with the US"),
    "ESP": (25, "Low"), "ITA": (32, "Fiscal stress"), "SWE": (25, "Baltic security"), "FIN": (35, "Russian border"),
    "NOR": (25, "Arctic, energy security"), "POL": (42, "Russia–NATO frontline"), "TUR": (60, "Lira, capital controls, regional wars"),
    "ISR": (75, "Regional war"), "ARE": (40, "Gulf security"), "EGY": (55, "FX shortage, Red Sea"),
    "MAR": (30, "Low"), "NGA": (60, "FX reform, security"), "KEN": (45, "Fiscal stress, protests"),
    "ZAF": (48, "Power, logistics, US trade preferences"), "GHA": (45, "Debt restructuring"),
    "CIV": (45, "Sahel spillover"), "SEN": (45, "Mining code revisions"), "BFA": (80, "Junta, jihadist insurgency"),
    "MLI": (82, "Junta, mine seizures"), "GIN": (65, "Bauxite and iron-ore nationalism"),
    "COD": (78, "Eastern conflict, cobalt export quotas"), "ZMB": (45, "Mining policy, debt"),
    "TZA": (45, "Mining disputes"), "UGA": (45, "Political risk"), "CMR": (55, "Separatist conflict"),
    "KAZ": (45, "Russia sanctions transit"), "MNG": (45, "Mining disputes"), "RUS": (90, "War, sanctions"),
    "UKR": (88, "War"), "IRN": (85, "Sanctions, regional war"), "PAK": (65, "Security, IMF programme"),
    "Other": (40, "Unattributed or global exposure"),
}
import json as _json
from pathlib import Path as _Path

COUNTRY_NAMES = {k: v["name"] for k, v in _json.loads((_Path(__file__).parent / "countries.json").read_text()).items()}


# ---- Dated events for the watchlist, mock. days = offset from as_of ----
EVENTS = [
    {"days": 21, "country": "CAN", "channel": "trade_tariffs", "severity": 4, "likelihood": .6,
     "title": "US decision on extending tariffs to Canadian energy and steel"},
    {"days": 45, "country": "CHN", "channel": "export_controls", "severity": 5, "likelihood": .5,
     "title": "New US export-control rule on advanced AI chips to China"},
    {"days": 90, "country": "TWN", "channel": "conflict_exposure", "severity": 5, "likelihood": .15,
     "title": "PLA exercises around Taiwan after the island's defence review"},
    {"days": 30, "ticker": "NVDA", "channel": "export_controls", "severity": 4, "likelihood": .5,
     "title": "NVIDIA licence decision for China-specific data-centre GPUs"},
    {"days": 60, "country": "MEX", "channel": "trade_tariffs", "severity": 3, "likelihood": .5,
     "title": "USMCA joint review deadline"},
    {"days": 14, "country": "USA", "channel": "regulatory", "severity": 3, "likelihood": .7,
     "title": "Court ruling on the legal basis for emergency tariffs"},
    {"days": 75, "ticker": "AAPL", "channel": "supply_chain", "severity": 3, "likelihood": .4,
     "title": "Apple assembly shift to India: Chinese export restrictions on equipment"},
    {"days": 40, "country": "SAU", "channel": "conflict_exposure", "severity": 4, "likelihood": .2,
     "title": "OPEC+ meeting amid Gulf shipping incidents"},
    {"days": 25, "ticker": "TSLA", "channel": "regulatory", "severity": 3, "likelihood": .5,
     "title": "EU countervailing duties review on China-built EVs"},
    {"days": 50, "country": "KOR", "channel": "conflict_exposure", "severity": 4, "likelihood": .1,
     "title": "North Korean missile tests ahead of joint US–ROK exercises"},
]

MOCK_SOURCE = {"title": "Mock data (placeholder until agents are connected)", "url": "", "locator": "web/mock.py"}
