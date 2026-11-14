"""The three personas from the case brief. Profile text comes from the brief; numeric limits
(crypto_max, max_single_weight) and the example portfolios are our own assumptions, editable in the form."""

PERSONAS = {
    "amira": {
        "label": "Amira",
        "tagline": "26 · software engineer · high risk · 15+ years",
        "brief": "Long-term growth. Interested in AI, emerging tech and crypto, "
                 "but does not want to hold only technology.",
        "profile": {"age": 26, "horizon_years": 15, "risk_tolerance": "high", "objective": "growth",
                    "experience": "intermediate", "esg_importance": "none", "avoid_controversies": False,
                    "crypto_max": 0.15, "max_single_weight": 0.25, "excluded_sectors": [],
                    "excluded_tickers": [], "avoid_countries": [],
                    "interests": ["ai", "emerging_tech", "crypto"], "notes": "Wants diversification beyond tech."},
        "portfolio": [("NVDA", 20), ("QQQ", 20), ("TSLA", 10), ("AMZN", 10), ("SHOP.TO", 10),
                      ("BTC-USD", 10), ("ETH-USD", 5), ("XIU.TO", 10), ("CNR.TO", 5)],
    },
    "mateo": {
        "label": "Mateo",
        "tagline": "41 · operations manager · moderate risk · 8–12 years",
        "brief": "Balanced growth. High importance on ESG, avoids companies with significant "
                 "environmental or social controversies, little interest in speculation.",
        "profile": {"age": 41, "horizon_years": 10, "risk_tolerance": "moderate", "objective": "balanced",
                    "experience": "intermediate", "esg_importance": "high", "avoid_controversies": True,
                    "crypto_max": 0.0, "max_single_weight": 0.15, "excluded_sectors": [],
                    "excluded_tickers": [], "avoid_countries": [],
                    "interests": ["energy_transition"], "notes": "Open to emerging tech if it fits the risk profile."},
        "portfolio": [("ESGV", 30), ("XBB.TO", 20), ("XIU.TO", 15), ("MSFT", 10), ("FTS.TO", 10),
                      ("JNJ", 5), ("ENB.TO", 5), ("XOM", 5)],
    },
    "robert": {
        "label": "Robert",
        "tagline": "59 · healthcare professional · low–moderate risk · 3–5 years",
        "brief": "Preserve capital with some growth, close to retirement. Prefers established "
                 "companies, little interest in crypto, tempted by highly publicised names.",
        "profile": {"age": 59, "horizon_years": 4, "risk_tolerance": "low_moderate", "objective": "preserve",
                    "experience": "advanced", "esg_importance": "none", "avoid_controversies": False,
                    "crypto_max": 0.0, "max_single_weight": 0.10, "excluded_sectors": [],
                    "excluded_tickers": [], "avoid_countries": [],
                    "interests": [], "notes": "Considering retirement in the next few years."},
        "portfolio": [("NVDA", 25), ("XBB.TO", 20), ("RY.TO", 15), ("TD.TO", 10), ("ZST.TO", 10),
                      ("JNJ", 10), ("PG", 10)],
    },
}

INTERESTS = [("ai", "Artificial intelligence"), ("emerging_tech", "Emerging technologies"),
             ("crypto", "Crypto assets"), ("energy_transition", "Energy transition"),
             ("dividends", "Dividend income"), ("canada", "Canadian companies")]

COUNTRIES = [("CHN", "China"), ("TWN", "Taiwan"), ("RUS", "Russia"), ("ISR", "Israel"),
             ("IRN", "Iran"), ("SAU", "Saudi Arabia"), ("IND", "India"), ("MEX", "Mexico"),
             ("USA", "United States"), ("CAN", "Canada")]
