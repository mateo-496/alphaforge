"""The three personas from the case brief. Profile text comes from the brief; numeric limits
(crypto_max, max_single_weight) and the example portfolios are our own assumptions, editable in the form."""

PERSONAS = {
    "amira": {
        "label": "Amira",
        "tagline": "26 · software engineer · high risk · 15+ years",
        "brief": "Long-term growth. Interested in AI, emerging tech and crypto, "
                 "but does not want to hold only technology.",
        "profile": {"age": 26, "horizon_years": 15, "risk_level": 5, "objective_level": 5,
                    "experience": "intermediate", "esg_importance": "none", "crypto_max": 0.15, "max_single_weight": 0.25,
                    "exclusions": [], "avoid_countries": [],
                    "interests": ["Artificial intelligence", "Semiconductors", "Crypto assets"],
                    "notes": "Wants diversification beyond technology."},
        "portfolio": [("NVDA", 20), ("QQQ", 20), ("TSLA", 10), ("AMZN", 10), ("SHOP.TO", 10),
                      ("BTC-USD", 10), ("ETH-USD", 5), ("XIU.TO", 10), ("CNR.TO", 5)],
    },
    "mateo": {
        "label": "Mateo",
        "tagline": "41 · operations manager · moderate risk · 8–12 years",
        "brief": "Balanced growth. High importance on ESG, avoids companies with significant "
                 "environmental or social controversies, little interest in speculation.",
        "profile": {"age": 41, "horizon_years": 10, "risk_level": 3, "objective_level": 3,
                    "experience": "intermediate", "esg_importance": "high", "crypto_max": 0.0, "max_single_weight": 0.15,
                    "exclusions": [], "avoid_countries": [],
                    "interests": ["Energy transition", "ESG leaders"],
                    "notes": "Open to emerging tech if it fits the risk profile."},
        "portfolio": [("ESGV", 30), ("XBB.TO", 20), ("XIU.TO", 15), ("MSFT", 10), ("FTS.TO", 10),
                      ("JNJ", 5), ("ENB.TO", 5), ("XOM", 5)],
    },
    "robert": {
        "label": "Robert",
        "tagline": "59 · healthcare professional · low–moderate risk · 3–5 years",
        "brief": "Preserve capital with some growth, close to retirement. Prefers established "
                 "companies, little interest in crypto, tempted by highly publicised names.",
        "profile": {"age": 59, "horizon_years": 4, "risk_level": 2, "objective_level": 1,
                    "experience": "advanced", "esg_importance": "none", "crypto_max": 0.0, "max_single_weight": 0.10,
                    "exclusions": [], "avoid_countries": [], "interests": ["Dividend income", "US large caps"],
                    "notes": "Considering retirement in the next few years."},
        "portfolio": [("NVDA", 25), ("XBB.TO", 20), ("RY.TO", 15), ("TD.TO", 10), ("ZST.TO", 10),
                      ("JNJ", 10), ("PG", 10)],
    },
}

