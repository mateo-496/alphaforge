"""Profile-fitted recommendations: deterministic, re-scored, empty when there is no immediate danger."""
import pytest

from agents import remediation_agent
from tools import risk_math
from web import recommend

UNI = {"NVDA": {"asset_class": "equity"}, "BTC-USD": {"asset_class": "crypto"},
       **{f: {"asset_class": c} for f, c in [("XBB.TO", "etf_bond"), ("AGG", "etf_bond"), ("SPY", "etf_equity"),
                                             ("ESGV", "etf_equity"), ("GLD", "etf_commodity")]}}
G = {"USA": .5, "TWN": .95, "CAN": .3, "Other": .6}


def parts(cw):
    return risk_math.holding_score(cw, G, 1.0, None)


def setup(p, weights):
    cands = recommend.candidates(p, weights, UNI)
    cw = {"XBB.TO": {"CAN": 1.0}, "AGG": {"USA": 1.0}, "SPY": {"USA": 1.0}, "ESGV": {"USA": 1.0}, "GLD": {"Other": 1.0}}
    hp = {"NVDA": parts({"TWN": .6, "USA": .4}), "BTC-USD": parts({"Other": 1.0})}
    return cands, {c: parts(cw[c]) for c in cands}, {c: cw[c] for c in cands}, hp


def test_profile_drives_the_fund():
    retiree = {"horizon_years": 4, "risk_level": 2, "objective_level": 1, "max_single_weight": .1}
    growth = {"horizon_years": 15, "risk_level": 5, "objective_level": 5, "max_single_weight": .25}
    esg = {"horizon_years": 10, "risk_level": 3, "objective_level": 3, "esg_importance": "high"}
    assert set(recommend.candidates(retiree, {}, UNI)) == {"XBB.TO", "AGG", "GLD", "SPY", "ESGV"}
    assert set(recommend.candidates(growth, {}, UNI)) == {"SPY", "ESGV"}           # no bonds for growth
    assert "SPY" not in recommend.candidates(esg, {}, UNI)                          # ESG funds only
    restricted = {**UNI, "SPY": {**UNI["SPY"], "sector": "Energy"}}
    assert "SPY" not in recommend.candidates({**growth, "excluded_sectors": ["Energy"]}, {}, restricted)
    assert recommend._fit("AGG", {"avoid_countries": ["TWN"]}, UNI, 20, {"TWN": .05}) is None


def test_clear_means_no_trade():
    p = {"horizon_years": 15, "risk_level": 5, "objective_level": 5, "max_single_weight": 1}
    cands, cp, ccw, hp = setup(p, {"NVDA": 1.0})
    hp["NVDA"] = parts({"USA": 1.0})                         # score 50, tolerance 70
    v = risk_math.verdict(risk_math.portfolio_score({"NVDA": 1.0}, hp)["P"], 5, 1.0, 0)
    assert v["clear"] and recommend.propose(p, {"NVDA": 1.0}, hp, cp, ccw, [], v, UNI, {}) == []


def test_limits_then_risk_with_rescoring():
    p = {"horizon_years": 4, "risk_level": 2, "objective_level": 1, "max_single_weight": .4, "crypto_max": 0.0}
    w = {"NVDA": .8, "BTC-USD": .2}
    cands, cp, ccw, hp = setup(p, w)
    checks = [{"ticker": "NVDA", "text": "NVDA is 80% of the portfolio, above the 40% single-holding limit."},
              {"ticker": "crypto", "text": "Crypto is 20% of the portfolio; the limit is 0%."}]
    P = risk_math.portfolio_score(w, hp)["P"]
    v = risk_math.verdict(P, 2, 1.0, len(checks))
    out = recommend.propose(p, w, hp, cp, ccw, checks, v, UNI, {"TWN": "Taiwan"})
    assert [s["kind"] for s in out[:2]] == ["profile", "profile"]
    assert out[0]["from"] == "NVDA" and abs(out[0]["fraction"] - .5) < 1e-9 and out[1]["from"] == "BTC-USD"
    assert all(s["to"] == "XBB.TO" for s in out)          # lowest-hazard bond fund for a retiree
    assert all(s["score_after"] < s["score_before"] for s in out) and out[-1]["score_after"] < P


def test_recommendations_respect_trade_preferences():
    profile = {"risk_level": 5, "objective_level": 5, "protected_holdings": ["NVDA"],
               "max_turnover": .1, "replacement_types": ["etf_bond"]}
    weights = {"NVDA": .5, "BTC-USD": .5}
    candidates, candidate_parts, candidate_cw, holding_parts = setup(profile, weights)
    assert set(candidates) == {"XBB.TO", "AGG"}
    checks = [{"ticker": "NVDA", "text": "NVDA is on the exclusion list."},
              {"ticker": "crypto", "text": "Crypto is above the limit."}]
    verdict = {"clear": False, "tolerance": 0}
    swaps = recommend.propose(profile, weights, holding_parts, candidate_parts, candidate_cw,
                              checks, verdict, UNI, {})
    assert swaps
    assert all(swap["from"] != "NVDA" and swap["to"] in candidates for swap in swaps)
    assert sum(swap["move"] for swap in swaps) <= .1 + 1e-9


def test_profile_conflicts_recomputed_for_simulated_holdings():
    from web import profile

    investor = {"risk_level": 2, "max_single_weight": .4, "crypto_max": 0,
                "excluded_sectors": ["Technology"], "avoid_countries": ["TWN"]}
    universe = {"NVDA": {"asset_class": "equity", "sector": "Technology"},
                "BTC-USD": {"asset_class": "crypto", "sector": ""},
                "AGG": {"asset_class": "etf_bond", "sector": ""}}
    exposure = {"NVDA": {"TWN": .5}, "BTC-USD": {"Other": 1}, "AGG": {"USA": 1}}
    before = profile.checks(investor, {"NVDA": .8, "BTC-USD": .2}, universe, "2026-11-12",
                            exposure, {"TWN": "Taiwan"}, vol_fn=lambda ticker, as_of: .5 if ticker == "NVDA" else None)
    after = profile.checks(investor, {"NVDA": .4, "AGG": .6}, universe, "2026-11-12",
                           exposure, {"TWN": "Taiwan"}, vol_fn=lambda ticker, as_of: .5 if ticker == "NVDA" else None)
    before_ids, after_ids = {item["id"] for item in before}, {item["id"] for item in after}
    assert {"single:NVDA", "crypto:limit", "sector:NVDA", "volatility:NVDA", "country:TWN"} <= before_ids
    assert after_ids == {"sector:NVDA", "volatility:NVDA", "country:TWN"}


def test_swap_explanations_report_partial_and_resolved_conflicts():
    from web import profile

    investor = {"risk_level": 5, "max_single_weight": .4, "crypto_max": 0, "max_turnover": .4,
                "protected_holdings": ["SAFE"], "replacement_types": ["etf_bond"]}
    universe = {"NVDA": {"asset_class": "equity", "sector": "Technology"},
                "SAFE": {"asset_class": "etf_equity", "sector": ""},
                "AGG": {"asset_class": "etf_bond", "sector": ""}}
    exposure = {"NVDA": {"TWN": 1}, "SAFE": {"USA": 1}, "AGG": {"USA": 1}}
    investor["avoid_countries"] = ["TWN"]
    swaps = [{"from": "NVDA", "to": "AGG", "move": .2}, {"from": "NVDA", "to": "AGG", "move": .2}]
    result = profile.assess_swaps(investor, {"NVDA": .8, "SAFE": .2}, swaps, universe, "2026-11-12",
                                  exposure, {"TWN": "Taiwan"}, vol_fn=lambda ticker, as_of: None)
    assert any(item["status"] == "remaining" and "single-holding" in item["text"]
               for item in swaps[0]["conflict_changes"])
    assert any(item["status"] == "resolved" and "single-holding" in item["text"]
               for item in swaps[1]["conflict_changes"])
    assert {item["id"] for item in result["resolved"]} == {"single:NVDA"}
    assert {item["id"] for item in result["remaining"]} == {"country:TWN"}
    assert "40.0% of the 40.0% limit" in swaps[1]["profile_notes"][0]
    assert "bond fund" in swaps[1]["profile_notes"][1]
    assert "SAFE" in swaps[1]["profile_notes"][2]


def test_swap_explanations_identify_new_volatility_conflict():
    from web import profile

    investor = {"risk_level": 2, "max_single_weight": 1, "crypto_max": 0}
    universe = {"NVDA": {"asset_class": "equity", "sector": "Technology"},
                "AGG": {"asset_class": "etf_bond", "sector": ""}}
    exposure = {"NVDA": {"USA": 1}, "AGG": {"USA": 1}}
    swaps = [{"from": "NVDA", "to": "AGG", "move": .25}]
    result = profile.assess_swaps(investor, {"NVDA": 1}, swaps, universe, "2026-11-12", exposure, {},
                                  vol_fn=lambda ticker, as_of: .4 if ticker == "AGG" else .1)
    assert [item["id"] for item in result["new"]] == ["volatility:AGG"]
    assert swaps[0]["conflict_changes"][0]["status"] == "new"


@pytest.mark.parametrize("sell,buy,fraction", [
    ("NVDA", "AGG", .2),
    ("AMD", "AGG", .5),
    ("AMD", "SPY", .2),
])
def test_agent_rejects_swaps_against_trade_preferences(monkeypatch, sell, buy, fraction):
    profile = {"protected_holdings": ["NVDA"], "max_turnover": .1, "replacement_types": ["etf_bond"]}
    weights = {"NVDA": .5, "AMD": .5}
    holdings = {ticker: {"G": 80} for ticker in weights}
    candidates = {"AGG": {"G": 20}, "SPY": {"G": 30}}
    universe = {ticker: {"name": ticker, "asset_class": asset_class} for ticker, asset_class in
                [("NVDA", "equity"), ("AMD", "equity"), ("AGG", "etf_bond"), ("SPY", "etf_equity")]}
    facts = remediation_agent.facts(profile, weights, holdings, candidates, 80, 50, [], universe)
    proposed = remediation_agent.Swaps(swaps=[
        {"sell": sell, "buy": buy, "fraction": fraction, "rationale": "Reduces risk."},
        {"sell": "AMD", "buy": "AGG", "fraction": .2, "rationale": "Reduces risk."},
    ])
    monkeypatch.setattr(remediation_agent.llm, "ask", lambda *args, **kwargs: proposed)
    swaps = remediation_agent.propose(facts, weights, holdings, candidates, [],
                                      score_fn=lambda portfolio: 100 * (portfolio["NVDA"] + portfolio["AMD"]))
    assert len(swaps) == 1
    assert swaps[0]["from"] == "AMD" and swaps[0]["to"] == "AGG"
    assert swaps[0]["move"] == pytest.approx(.1)


def test_agent_uses_verified_holding_evidence(monkeypatch):
    profile = {"max_turnover": 1}
    weights = {"NVDA": 1.0}
    holdings = {"NVDA": {"G": 80}}
    candidates = {"AGG": {"G": 20}}
    universe = {"NVDA": {"name": "Nvidia", "asset_class": "equity"},
                "AGG": {"name": "Bond fund", "asset_class": "etf_bond"}}
    report = {"firms": {"NVDA": {"claims": [
        {"verified": True, "quote": "Export controls could limit sales.", "url": "https://example.com/filing"},
        {"verified": False, "quote": "Invented risk.", "url": "https://example.com/other"},
    ]}}}
    facts = remediation_agent.facts(profile, weights, holdings, candidates, 80, 50, [], universe, report)
    assert len(facts["evidence"]) == 1
    evidence_id = facts["evidence"][0]["id"]
    proposed = remediation_agent.Swaps(swaps=[
        {"sell": "NVDA", "buy": "AGG", "fraction": .5, "rationale": "An unsupported claim.",
         "evidence_ids": [evidence_id, "invented"]},
    ])
    monkeypatch.setattr(remediation_agent.llm, "ask", lambda *args, **kwargs: proposed)
    swaps = remediation_agent.propose(facts, weights, holdings, candidates, [],
                                      score_fn=lambda portfolio: 100 * portfolio["NVDA"])
    assert len(swaps) == 1
    assert swaps[0]["evidence"] == [facts["evidence"][0]]
    assert "unsupported claim" not in swaps[0]["rationale"]


def test_agent_context_includes_verified_reports_and_profile():
    profile = {"avoid_countries": ["TWN"], "max_single_weight": .25, "excluded_sectors": ["Energy"]}
    universe = {"NVDA": {"name": "Nvidia", "asset_class": "equity"},
                "AGG": {"name": "Bond fund", "asset_class": "etf_bond"}}
    report = {"as_of": "2026-11-12", "checks": [{"ticker": "TWN", "text": "Taiwan limit"}],
              "assets": {"NVDA": {"country_weights": {"TWN": .5}}},
              "by_holding": [{"ticker": "NVDA", "share": .8, "estimated": True, "method": "prior"}],
              "by_country": [{"iso3": "TWN", "name": "Taiwan", "holdings": ["NVDA"]}],
              "scenario_sets": [{"scope": "global", "computed_at": "2026-11-12T10:00:00"},
                                {"scope": "future", "computed_at": "2026-11-13T10:00:00"}],
              "scenarios": [{"scope": "global", "name": "Trade disruption", "holdings": ["NVDA"], "exposure": .5,
                             "evidence": [{"quote_verified": True, "quote": "Verified scenario text",
                                           "url": "https://example.com/scenario"},
                                          {"quote_verified": False, "quote": "Not verified",
                                           "url": "https://example.com/rejected"}]},
                            {"scope": "future", "name": "Future", "holdings": ["NVDA"],
                             "evidence": [{"quote_verified": True, "quote": "Future quote",
                                           "url": "https://example.com/future"}]}],
              "macro": {"countries": {"TWN": {"indicators": {"growth": {"label": "Growth", "value": 2,
                                                                           "year": 2025, "url": "https://example.com/wb"}}}}},
              "gpr_claims": {"TWN": {"claims": [{"quote_verified": True, "evidence_quote": '"gprc": 1',
                                                    "sources": [{"url": "https://example.com/gpr"}]}]}}}
    facts = remediation_agent.facts(profile, {"NVDA": 1}, {"NVDA": {"G": 80}}, {"AGG": {"G": 20}},
                                    80, 50, [], universe, report)
    assert facts["profile"]["avoid_countries"] == ["TWN"] and facts["conflicts"] == report["checks"]
    assert facts["holdings"][0]["exposure"] == {"TWN": .5}
    assert facts["holdings"][0]["exposure_estimated"] is True
    assert facts["countries"][0]["indicators"][0]["url"] == "https://example.com/wb"
    assert [scenario["name"] for scenario in facts["scenarios"]] == ["Trade disruption"]
    assert {item["kind"] for item in facts["evidence"]} == {"Scenario source", "GPR data"}
    assert all(item["ticker"] == "NVDA" and item["quote"] not in ("Not verified", "Future quote")
               for item in facts["evidence"])


def test_agent_trade_size_is_computed_by_code(monkeypatch):
    profile = {"max_turnover": .3}
    weights = {"NVDA": 1.0}
    holdings = {"NVDA": {"G": 80}}
    candidates = {"AGG": {"G": 20}}
    universe = {"NVDA": {"name": "Nvidia", "asset_class": "equity"},
                "AGG": {"name": "Bond fund", "asset_class": "etf_bond"}}
    facts = remediation_agent.facts(profile, weights, holdings, candidates, 80, 50, [], universe)

    def run(fraction):
        proposed = remediation_agent.Swaps(swaps=[
            {"sell": "NVDA", "buy": "AGG", "fraction": fraction, "rationale": "Reduces risk."},
        ])
        monkeypatch.setattr(remediation_agent.llm, "ask", lambda *args, **kwargs: proposed)
        return remediation_agent.propose(facts, weights, holdings, candidates, [],
                                         score_fn=lambda portfolio: 100 * portfolio["NVDA"])

    assert run(.1)[0]["move"] == pytest.approx(.3)
    assert run(.9)[0]["move"] == pytest.approx(.3)


def test_agent_excludes_filing_after_analysis_date():
    report = {"as_of": "2026-11-12", "firms": {"NVDA": {
        "claims": [{"verified": True, "quote": "A later filing.", "url": "https://example.com/filing"}],
        "risk_factors": {"status": "ok", "filing_date": "2026-11-13", "url": "https://example.com/filing",
                         "risks": [{"quote": "Later risk."}]}}}}
    universe = {"NVDA": {"name": "Nvidia", "asset_class": "equity"},
                "AGG": {"name": "Bond fund", "asset_class": "etf_bond"}}
    facts = remediation_agent.facts({}, {"NVDA": 1}, {"NVDA": {"G": 80}}, {"AGG": {"G": 20}},
                                    80, 50, [], universe, report)
    assert facts["evidence"] == []
