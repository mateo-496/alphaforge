from core.schemas import DraftScenario, ScenarioEvidence, ScenarioSet
from pipelines.scenarios import merge

EV = [ScenarioEvidence(source_id="x", url="u", quote="q", quote_verified=True)]


def d(id, name, lk, countries, impact=3):
    return DraftScenario(id=id, name=name, summary="s", countries=countries, channels=["trade_tariffs"],
                         likelihood=lk, impact=impact, signposts=["a"], evidence=EV)


def first():
    return merge(None, [d("taiwan-blockade", "Taiwan Strait blockade", .2, {"TWN": 1, "CHN": .8}),
                        d("old-risk", "Old risk", .3, {"FRA": 1})], "global", .35, "q1", 15)


def test_new_scenarios_enter_at_fresh_values():
    s = {x.id: x for x in first().scenarios}
    assert s["taiwan-blockade"].likelihood == .2 and s["taiwan-blockade"].status == "new"


def test_ema_and_decay():
    prev = first()
    nxt = merge(prev, [d("taiwan-blockade", "Taiwan Strait blockade", .4, {"TWN": 1, "JPN": .6})],
                "global", .35, "q2", 15)
    s = {x.id: x for x in nxt.scenarios}
    t = s["taiwan-blockade"]
    assert abs(t.likelihood - (.35 * .4 + .65 * .2)) < 1e-9          # 0.27
    assert abs(t.countries["CHN"] - .65 * .8) < 1e-9                 # absent country decays
    assert abs(t.countries["JPN"] - .35 * .6) < 1e-9                 # new country phases in
    assert t.status == "continuing" and t.weeks_seen == 2
    assert s["old-risk"].status == "fading" and abs(s["old-risk"].likelihood - .3 * .65) < 1e-9
    assert nxt.query_keys == ["q1", "q2"]


def test_renamed_scenario_keeps_id():
    prev = first()
    nxt = merge(prev, [d("taiwan-quarantine", "Taiwan blockade by China", .2, {"TWN": 1})], "global", .35, "q2", 15)
    t = {x.id: x for x in nxt.scenarios}["taiwan-blockade"]
    assert t.status == "continuing" and t.name == "Taiwan blockade by China"
    assert "taiwan-quarantine" not in {x.id for x in nxt.scenarios}


def test_dropped_after_three_missing_weeks():
    s = first()
    for k in range(3):
        s = merge(s, [d("taiwan-blockade", "Taiwan Strait blockade", .2, {"TWN": 1})], "global", .35, f"q{k}", 15)
    assert "old-risk" not in {x.id for x in s.scenarios}
