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
    "Other": (40, "Unattributed or global exposure"),
}
COUNTRY_NAMES = {"USA": "United States", "CAN": "Canada", "CHN": "China", "TWN": "Taiwan", "MEX": "Mexico",
                 "GBR": "United Kingdom", "DEU": "Germany", "JPN": "Japan", "KOR": "South Korea", "IND": "India",
                 "SAU": "Saudi Arabia", "QAT": "Qatar", "IRL": "Ireland", "NLD": "Netherlands",
                 "SGP": "Singapore", "PRK": "North Korea", "RUS": "Russia", "UKR": "Ukraine", "POL": "Poland",
                 "FIN": "Finland", "IRN": "Iran", "ISR": "Israel", "ARE": "United Arab Emirates",
                 "IRQ": "Iraq", "PHL": "Philippines", "VNM": "Vietnam", "EST": "Estonia", "LTU": "Lithuania",
                 "LVA": "Latvia", "Other": "Other / global"}

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

# ---- Precomputed scenarios (weekly job in production). intensity 0-1 per country ----
SCENARIOS = [
    {"id": "taiwan", "name": "Taiwan Strait blockade",
     "description": "Naval blockade of Taiwan; semiconductor supply halted, sanctions on China.",
     "countries": {"TWN": 1.0, "CHN": .85, "JPN": .55, "KOR": .5, "USA": .4, "PHL": .45, "SGP": .3, "VNM": .3}},
    {"id": "korea", "name": "War on the Korean peninsula",
     "description": "Armed conflict between the Koreas drawing in the US and Japan.",
     "countries": {"PRK": 1.0, "KOR": 1.0, "JPN": .7, "USA": .45, "CHN": .4}},
    {"id": "us_canada", "name": "US–Canada tariff escalation",
     "description": "25% US tariffs on most Canadian goods incl. energy; Canadian retaliation.",
     "countries": {"CAN": 1.0, "USA": .6, "MEX": .5}},
    {"id": "gulf", "name": "Gulf oil supply shock",
     "description": "Strait of Hormuz closed for weeks; oil above $130.",
     "countries": {"IRN": 1.0, "SAU": .85, "ARE": .8, "QAT": .8, "IRQ": .75, "ISR": .5}},
    {"id": "russia_nato", "name": "Russia–NATO confrontation",
     "description": "Incident in the Baltics escalates; new sanctions and energy disruption in Europe.",
     "countries": {"RUS": 1.0, "UKR": .8, "EST": .85, "LVA": .85, "LTU": .85, "POL": .7, "FIN": .6, "DEU": .45}},
    {"id": "chips", "name": "US–China chip decoupling",
     "description": "Full ban on advanced chip and equipment sales to China; China restricts critical minerals.",
     "countries": {"CHN": 1.0, "TWN": .6, "USA": .55, "KOR": .45, "NLD": .4, "JPN": .35}},
]

MOCK_SOURCE = {"title": "Mock data (placeholder until agents are connected)", "url": "", "locator": "web/mock.py"}
