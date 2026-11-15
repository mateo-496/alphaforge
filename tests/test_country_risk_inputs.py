import pandas as pd
import pytest

from tools import country_risk_inputs as cri


@pytest.fixture
def frame(monkeypatch):
    months = pd.date_range("2010-01-01", "2026-10-01", freq="MS")
    # TWN rises sharply at the end; USA is flat
    twn = [0.1] * (len(months) - 12) + [0.5] * 12
    usa = [2.0] * len(months)
    df = pd.DataFrame({"month": months, "gprc_twn": twn, "gprc_usa": usa})
    monkeypatch.setattr(cri, "_gpr_frame", lambda: (df, {"taiwan": "TWN", "united states": "USA"}))
    monkeypatch.setattr(cri, "stress_percentile", lambda as_of: {"percentile": 0.5, "latest": 0.1, "date": as_of})
    return df


def test_resolve_iso3_accepts_iso2_iso3_and_names(frame):
    assert cri.resolve_iso3("TW") == "TWN"
    assert cri.resolve_iso3("twn") == "TWN"
    assert cri.resolve_iso3("Taiwan") == "TWN"
    assert cri.resolve_iso3("Atlantis") is None


def test_gpr_percentile_is_relative_to_own_history_not_level(frame):
    twn = cri.gpr_percentile("TWN", "2026-10-31")
    usa = cri.gpr_percentile("USA", "2026-10-31")
    assert twn["percentile"] == 1.0 and twn["current_12m_mean"] == pytest.approx(0.5)
    assert usa["percentile"] == 1.0  # flat series: current equals every past value
    assert cri.gpr_percentile("TWN", "2015-12-31")["percentile"] == 1.0
    assert cri.gpr_percentile("TWN", "2010-12-31") is None  # not enough history
    assert cri.gpr_percentile("XXX", "2026-10-31") is None


def test_country_risk_score_reports_missing_inputs_instead_of_inventing(frame):
    known = cri.country_risk_score("TW", "2026-10-31")
    assert known["score"] == pytest.approx((1.0 + 0.5) / 2)
    assert known["missing_inputs"] == ["epu"]
    unknown = cri.country_risk_score("SG", "2026-10-31")
    assert unknown["score"] == pytest.approx(0.5)  # only global stress is available
    assert unknown["missing_inputs"] == ["gpr", "epu"]
