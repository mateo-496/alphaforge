"""Tests for tools.portfolio_score — deterministic portfolio risk scoring.

Covers:
  - Worked example (exact numbers from specification)
  - Determinism (same inputs → same outputs)
  - Boundary conditions (all zeros, all ones, all 0.5)
  - Missing / invalid score handling (None, NaN, confidence=0)
  - Monotonicity spot checks
  - Separation (tolerance does NOT change objective score)
  - Reference calibration points (uniform inputs, same-portfolio-different-users)
  - Helper function edge cases
"""

import math
import unittest

from tools.portfolio_score import Params, _clamp, _f, _sig, portfolio_scores


class TestHelpers(unittest.TestCase):
    """Unit tests for internal helper functions."""

    # ── _f (normalized exponential transform) ────────────────────
    def test_f_endpoints(self):
        """f(0) = 0 and f(1) = 1 for any λ > 0."""
        for lam in [0.5, 1.0, 2.0, 5.0, 10.0]:
            self.assertAlmostEqual(_f(0.0, lam), 0.0, places=12)
            self.assertAlmostEqual(_f(1.0, lam), 1.0, places=12)

    def test_f_identity_at_zero_lambda(self):
        """When λ = 0 the transform is the identity."""
        for x in [0.0, 0.25, 0.5, 0.75, 1.0]:
            self.assertAlmostEqual(_f(x, 0.0), x, places=12)

    def test_f_monotonicity(self):
        """f is strictly increasing on [0, 1]."""
        lam = 2.0
        prev = _f(0.0, lam)
        for i in range(1, 101):
            x = i / 100.0
            cur = _f(x, lam)
            self.assertGreater(cur, prev)
            prev = cur

    def test_f_convexity(self):
        """f is strictly convex: midpoint is below the secant."""
        lam = 2.0
        for a_val, b_val in [(0.0, 1.0), (0.2, 0.8), (0.1, 0.5)]:
            mid = (a_val + b_val) / 2.0
            self.assertLess(_f(mid, lam), (_f(a_val, lam) + _f(b_val, lam)) / 2.0)

    # ── _sig (logistic) ─────────────────────────────────────────
    def test_sig_at_zero(self):
        self.assertAlmostEqual(_sig(0.0), 0.5, places=12)

    def test_sig_symmetry(self):
        """σ(z) + σ(−z) = 1."""
        for z in [0.5, 1.0, 3.0, 10.0, 50.0]:
            self.assertAlmostEqual(_sig(z) + _sig(-z), 1.0, places=12)

    def test_sig_large_positive(self):
        self.assertAlmostEqual(_sig(100.0), 1.0, places=12)

    def test_sig_large_negative(self):
        self.assertAlmostEqual(_sig(-100.0), 0.0, places=12)

    # ── _clamp ──────────────────────────────────────────────────
    def test_clamp_none(self):
        self.assertEqual(_clamp(None), 0.5)

    def test_clamp_nan(self):
        self.assertEqual(_clamp(float("nan")), 0.5)

    def test_clamp_in_range(self):
        self.assertEqual(_clamp(0.3), 0.3)

    def test_clamp_below(self):
        self.assertEqual(_clamp(-0.5), 0.0)

    def test_clamp_above(self):
        self.assertEqual(_clamp(1.5), 1.0)


class TestWorkedExample(unittest.TestCase):
    """Exact reproduction of the specification's worked example."""

    def test_main_example(self):
        result = portfolio_scores(0.45, 0.70, 0.55, 0.4, conf=(0.9, 0.6, 1.0))
        self.assertEqual(result["objective"], 58.74)
        self.assertEqual(result["personalized"], 78.01)
        self.assertEqual(result["confidence"], 0.81)


class TestDeterminism(unittest.TestCase):
    """Identical inputs must always produce identical outputs."""

    def test_repeated_calls(self):
        args = (0.45, 0.70, 0.55, 0.4)
        kwargs = {"conf": (0.9, 0.6, 1.0)}
        first = portfolio_scores(*args, **kwargs)
        for _ in range(100):
            again = portfolio_scores(*args, **kwargs)
            self.assertEqual(first, again)

    def test_default_params_repeated(self):
        r1 = portfolio_scores(0.5, 0.5, 0.5, 0.5)
        r2 = portfolio_scores(0.5, 0.5, 0.5, 0.5)
        self.assertEqual(r1, r2)


class TestBoundaries(unittest.TestCase):
    """Edge cases: all zeros, all ones, all neutral."""

    def test_all_zeros(self):
        r = portfolio_scores(0.0, 0.0, 0.0, 0.5)
        self.assertAlmostEqual(r["objective"], 0.0, places=2)
        self.assertGreaterEqual(r["personalized"], 0.0)

    def test_all_ones(self):
        r = portfolio_scores(1.0, 1.0, 1.0, 0.5)
        self.assertAlmostEqual(r["objective"], 100.0, places=2)
        self.assertAlmostEqual(r["personalized"], 100.0, places=1)

    def test_all_half(self):
        r = portfolio_scores(0.5, 0.5, 0.5, 0.5)
        self.assertGreater(r["objective"], 0.0)
        self.assertLess(r["objective"], 100.0)
        self.assertGreater(r["personalized"], 0.0)
        self.assertLess(r["personalized"], 100.0)

    def test_output_ranges(self):
        """Scores always stay in [0, 100], confidence in [0, 1]."""
        import random
        random.seed(42)
        for _ in range(500):
            a1, a2, a3, t = [random.random() for _ in range(4)]
            c = tuple(random.random() for _ in range(3))
            r = portfolio_scores(a1, a2, a3, t, conf=c)
            self.assertGreaterEqual(r["objective"], 0.0)
            self.assertLessEqual(r["objective"], 100.0)
            self.assertGreaterEqual(r["personalized"], 0.0)
            self.assertLessEqual(r["personalized"], 100.0)
            self.assertGreaterEqual(r["confidence"], 0.0)
            self.assertLessEqual(r["confidence"], 1.0)


class TestMissingScores(unittest.TestCase):
    """None, NaN, and zero-confidence inputs are handled safely."""

    def test_none_inputs_dont_crash(self):
        r = portfolio_scores(None, None, None, None)
        self.assertIsInstance(r["objective"], float)
        self.assertIsInstance(r["personalized"], float)

    def test_nan_inputs_dont_crash(self):
        nan = float("nan")
        r = portfolio_scores(nan, nan, nan, nan)
        self.assertFalse(math.isnan(r["objective"]))
        self.assertFalse(math.isnan(r["personalized"]))

    def test_zero_confidence_shrinks_to_prior(self):
        """With c=0, all inputs shrink to μ=0.5 regardless of raw values."""
        r_low  = portfolio_scores(0.0, 0.0, 0.0, 0.5, conf=(0.0, 0.0, 0.0))
        r_high = portfolio_scores(1.0, 1.0, 1.0, 0.5, conf=(0.0, 0.0, 0.0))
        # Both should equal the μ=0.5 baseline since confidence is 0
        self.assertAlmostEqual(r_low["objective"], r_high["objective"], places=6)


class TestMonotonicity(unittest.TestCase):
    """Increasing any risk input should increase the objective score (spot checks)."""

    def test_increasing_a1(self):
        prev = portfolio_scores(0.0, 0.5, 0.5, 0.5)["objective"]
        for a1 in [0.2, 0.4, 0.6, 0.8, 1.0]:
            cur = portfolio_scores(a1, 0.5, 0.5, 0.5)["objective"]
            self.assertGreaterEqual(cur, prev, f"Non-monotone at A1={a1}")
            prev = cur

    def test_increasing_a2(self):
        prev = portfolio_scores(0.5, 0.0, 0.5, 0.5)["objective"]
        for a2 in [0.2, 0.4, 0.6, 0.8, 1.0]:
            cur = portfolio_scores(0.5, a2, 0.5, 0.5)["objective"]
            self.assertGreaterEqual(cur, prev, f"Non-monotone at A2={a2}")
            prev = cur

    def test_increasing_a3(self):
        prev = portfolio_scores(0.5, 0.5, 0.0, 0.5)["objective"]
        for a3 in [0.2, 0.4, 0.6, 0.8, 1.0]:
            cur = portfolio_scores(0.5, 0.5, a3, 0.5)["objective"]
            self.assertGreaterEqual(cur, prev, f"Non-monotone at A3={a3}")
            prev = cur


class TestSeparation(unittest.TestCase):
    """User tolerance must NOT change the objective score."""

    def test_tolerance_does_not_affect_objective(self):
        base = portfolio_scores(0.45, 0.70, 0.55, 0.1, conf=(0.9, 0.6, 1.0))
        for t in [0.2, 0.4, 0.6, 0.8, 1.0]:
            r = portfolio_scores(0.45, 0.70, 0.55, t, conf=(0.9, 0.6, 1.0))
            self.assertEqual(r["objective"], base["objective"],
                             f"Objective changed at t={t}")

    def test_higher_tolerance_lowers_personalized(self):
        """More tolerance → less concern (personalized score decreases)."""
        prev = portfolio_scores(0.5, 0.5, 0.5, 0.0)["personalized"]
        for t in [0.2, 0.4, 0.6, 0.8, 1.0]:
            cur = portfolio_scores(0.5, 0.5, 0.5, t)["personalized"]
            self.assertLessEqual(cur, prev, f"Personalized not decreasing at t={t}")
            prev = cur


class TestCalibrationPoints(unittest.TestCase):
    """Reference calibration values from the specification."""

    def test_uniform_03(self):
        r = portfolio_scores(0.3, 0.3, 0.3, 0.5)
        self.assertAlmostEqual(r["objective"], 31.6, places=1)

    def test_uniform_07(self):
        r = portfolio_scores(0.7, 0.7, 0.7, 0.5)
        self.assertAlmostEqual(r["objective"], 73.7, places=1)

    def test_uniform_09(self):
        r = portfolio_scores(0.9, 0.9, 0.9, 0.5)
        self.assertAlmostEqual(r["objective"], 93.3, places=1)

    def test_uniform_08(self):
        r = portfolio_scores(0.8, 0.8, 0.8, 0.5)
        self.assertAlmostEqual(r["objective"], 83.9, delta=0.5)

    def test_same_portfolio_different_users(self):
        """A₁=A₂=A₃=0.5 with t∈{0.1, 0.5, 0.9}."""
        expected = {
            0.1: {"objective": 53.12, "personalized": 91.23},
            0.5: {"objective": 53.12, "personalized": 56.45},
            0.9: {"objective": 53.12, "personalized": 13.90},
        }
        for t, exp in expected.items():
            r = portfolio_scores(0.5, 0.5, 0.5, t)
            self.assertAlmostEqual(r["objective"], exp["objective"], places=1,
                                   msg=f"objective at t={t}")
            self.assertAlmostEqual(r["personalized"], exp["personalized"], places=1,
                                   msg=f"personalized at t={t}")


class TestCustomParams(unittest.TestCase):
    """Verify that parameters are truly configurable."""

    def test_different_params_give_different_scores(self):
        default = portfolio_scores(0.5, 0.5, 0.5, 0.5)
        custom_p = Params(lam=4.0, eta=0.5, kappa=0.4)
        custom = portfolio_scores(0.5, 0.5, 0.5, 0.5, p=custom_p)
        self.assertNotEqual(default["objective"], custom["objective"])

    def test_params_frozen(self):
        """Params dataclass is immutable."""
        p = Params()
        with self.assertRaises(AttributeError):
            p.lam = 5.0  # type: ignore[misc]


class TestApplicationIntegration(unittest.TestCase):
    """Tests covering extract_agent_inputs, calculate_portfolio_risk, and end-to-end integration."""

    def test_parse_tolerance(self):
        from tools.portfolio_score import parse_tolerance
        self.assertEqual(parse_tolerance("low"), 0.20)
        self.assertEqual(parse_tolerance("LOW"), 0.20)
        self.assertEqual(parse_tolerance("low_moderate"), 0.40)
        self.assertEqual(parse_tolerance("low-moderate"), 0.40)
        self.assertEqual(parse_tolerance("moderate"), 0.60)
        self.assertEqual(parse_tolerance("high"), 0.85)
        self.assertEqual(parse_tolerance(0.35), 0.35)
        self.assertEqual(parse_tolerance(40.0), 0.40)  # auto-scaled percentage
        self.assertEqual(parse_tolerance(None), 0.50)
        self.assertEqual(parse_tolerance(float("nan")), 0.50)
        self.assertEqual(parse_tolerance("unknown_persona_xyz"), 0.50)

    def test_extract_agent_inputs_realistic(self):
        from tools.portfolio_score import extract_agent_inputs
        weights = {"NVDA": 0.6, "RY.TO": 0.4}
        assets = {
            "NVDA": {"country_weights": {"USA": 0.5, "TWN": 0.5}, "firm_score": 4.0},
            "RY.TO": {"country_weights": {"CAN": 0.7, "USA": 0.3}, "firm_score": 1.5},
        }
        countries = {
            "USA": {"R": 38.0},
            "CAN": {"R": 32.0},
            "TWN": {"R": 68.0},
        }
        scenarios = [
            {
                "scenarios": [
                    {"name": "Taiwan crisis", "likelihood": 0.4, "impact": 4, "countries": {"TWN": 1.0}}
                ]
            }
        ]
        profile = {"risk_tolerance": "moderate"}

        a1, a2, a3, tol, conf = extract_agent_inputs(weights, profile, assets, countries, scenarios)
        self.assertGreater(a1, 0.0)
        self.assertLessEqual(a1, 1.0)
        self.assertGreater(a2, 0.0)
        self.assertLessEqual(a2, 1.0)
        self.assertGreater(a3, 0.0)
        self.assertLessEqual(a3, 1.0)
        self.assertEqual(tol, 0.60)
        self.assertEqual(len(conf), 3)

    def test_calculate_portfolio_risk_with_profile(self):
        from tools.portfolio_score import calculate_portfolio_risk
        weights = {"NVDA": 0.5, "AAPL": 0.5}
        assets = {
            "NVDA": {"country_weights": {"USA": 0.6, "TWN": 0.4}, "firm_score": 4.0},
            "AAPL": {"country_weights": {"USA": 0.8, "CHN": 0.2}, "firm_score": 3.0},
        }
        countries = {
            "USA": {"R": 35.0},
            "TWN": {"R": 65.0},
            "CHN": {"R": 70.0},
        }
        # Run with conservative user
        r_low = calculate_portfolio_risk(weights, {"risk_tolerance": "low"}, assets, countries)
        # Run with aggressive user
        r_high = calculate_portfolio_risk(weights, {"risk_tolerance": "high"}, assets, countries)

        # Objective risk must be identical for both users
        self.assertEqual(r_low["objective"], r_high["objective"])
        # Personalized concern must be higher for the low-tolerance user
        self.assertGreater(r_low["personalized"], r_high["personalized"])
        self.assertEqual(r_low["score"], r_low["personalized"])
        self.assertIn("components", r_low)
        self.assertIn("confidences", r_low)

    def test_calculate_portfolio_risk_determinism(self):
        from tools.portfolio_score import calculate_portfolio_risk
        weights = {"NVDA": 0.7, "SHOP.TO": 0.3}
        assets = {
            "NVDA": {"country_weights": {"USA": 0.5, "TWN": 0.5}, "firm_score": 4.0},
            "SHOP.TO": {"country_weights": {"USA": 0.7, "CAN": 0.3}, "firm_score": 2.0},
        }
        countries = {"USA": {"R": 38.0}, "TWN": {"R": 68.0}, "CAN": {"R": 32.0}}
        profile = {"risk_tolerance": "low_moderate"}

        first = calculate_portfolio_risk(weights, profile, assets, countries)
        for _ in range(50):
            again = calculate_portfolio_risk(weights, profile, assets, countries)
            self.assertEqual(first, again)

    def test_calculate_portfolio_risk_empty_and_edge_inputs(self):
        from tools.portfolio_score import calculate_portfolio_risk
        # Empty inputs should not crash and return valid numbers
        r_empty = calculate_portfolio_risk({}, {}, {}, {}, [])
        self.assertIsInstance(r_empty["score"], float)
        self.assertGreaterEqual(r_empty["score"], 0.0)
        self.assertLessEqual(r_empty["score"], 100.0)

        # None inputs
        r_none = calculate_portfolio_risk(None, None, None, None, None)
        self.assertIsInstance(r_none["score"], float)

        # Single holding 100%
        r_single = calculate_portfolio_risk(
            weights={"AAPL": 1.0},
            profile={"risk_tolerance": "moderate"},
            assets={"AAPL": {"country_weights": {"USA": 1.0}, "firm_score": 2.0}},
            countries={"USA": {"R": 30.0}},
        )
        self.assertGreater(r_single["score"], 0.0)
        self.assertLess(r_single["score"], 100.0)


if __name__ == "__main__":
    unittest.main()


class TestRangeAndRealism(unittest.TestCase):
    """Guards against the score collapsing into a narrow band again."""

    def test_uniform_inputs_map_near_themselves(self):
        for x in (0.1, 0.3, 0.5, 0.7, 0.9):
            r = portfolio_scores(x, x, x, 0.5)["objective"] / 100.0
            self.assertLess(abs(r - x), 0.05, msg=f"uniform {x} -> {r}")

    def test_full_range_used(self):
        import itertools
        grid = [i / 10 for i in range(11)]
        objs = [portfolio_scores(a, b, c, 0.5, conf=(0.9, 0.9, 0.9))["objective"]
                for a, b, c in itertools.product(grid, repeat=3)]
        self.assertLess(min(objs), 10.0)
        self.assertGreater(max(objs), 90.0)

    def test_worst_block_dominates(self):
        """One very risky block lifts the score above the plain weighted average."""
        r = portfolio_scores(0.1, 0.9, 0.1, 0.5)["objective"] / 100.0
        self.assertGreater(r, 0.6 * 0.1 + 0.4 * 0.9)


class TestCalibrationHelpers(unittest.TestCase):
    def test_calibrate_fixed_points(self):
        from tools.portfolio_score import calibrate
        for mid, k in ((0.4, 2.0), (0.5, 1.5), (0.3, 3.0)):
            self.assertEqual(calibrate(0.0, mid, k), 0.0)
            self.assertEqual(calibrate(1.0, mid, k), 1.0)
            self.assertAlmostEqual(calibrate(mid, mid, k), 0.5, places=12)

    def test_calibrate_identity(self):
        from tools.portfolio_score import calibrate
        for x in (0.1, 0.37, 0.8):
            self.assertAlmostEqual(calibrate(x, 0.5, 1.0), x, places=12)

    def test_calibrate_monotone(self):
        from tools.portfolio_score import calibrate
        xs = [i / 50 for i in range(51)]
        ys = [calibrate(x, 0.4, 2.0) for x in xs]
        self.assertEqual(ys, sorted(ys))

    def test_power_mean(self):
        from tools.portfolio_score import power_mean
        self.assertIsNone(power_mean([], 2.0))
        self.assertAlmostEqual(power_mean([(0.3, 1.0), (0.3, 2.0)], 2.0), 0.3)
        self.assertAlmostEqual(power_mean([(0.2, 1.0), (0.8, 1.0)], 1.0), 0.5)
        self.assertGreater(power_mean([(0.2, 1.0), (0.8, 1.0)], 2.0), 0.5)


class TestScenarioRisk(unittest.TestCase):
    def _inputs(self, weights, scenarios):
        from tools.portfolio_score import extract_agent_inputs
        assets = {"A": {"country_weights": {"TWN": 1.0}, "firm_score": 2.5},
                  "B": {"country_weights": {"CAN": 1.0}, "firm_score": 2.5}}
        countries = {"TWN": {"R": 68}, "CAN": {"R": 32}}
        return extract_agent_inputs(weights, None, assets, countries, scenarios)

    def test_scenarios_add_up(self):
        """Adding a dangerous scenario never lowers A2 (a mean would dilute it)."""
        s1 = {"likelihood": 0.1, "impact": 2, "countries": {"TWN": 1.0}}
        s2 = {"likelihood": 0.3, "impact": 5, "countries": {"TWN": 1.0}}
        a2_one = self._inputs({"A": 1.0}, [s1])[1]
        a2_two = self._inputs({"A": 1.0}, [s1, s2])[1]
        self.assertGreater(a2_two, a2_one)

    def test_exposure_follows_weights(self):
        """A stale precomputed exposure must not override the portfolio's own country mix."""
        s = {"likelihood": 0.3, "impact": 5, "countries": {"TWN": 1.0}, "exposure": 0.9}
        exposed = self._inputs({"A": 1.0}, [s])[1]
        unexposed = self._inputs({"B": 1.0}, [s])[1]
        self.assertGreater(exposed, 0.5)
        self.assertEqual(unexposed, 0.0)
