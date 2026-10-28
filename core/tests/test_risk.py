"""Unit tests for core/services/risk.py."""
import unittest

from core.services.risk import (
    compute_risk,
    habit_rate,
    monte_carlo_distribution,
    probability_finish_safe,
    risk_label,
)


class TestHabitRate(unittest.TestCase):
    def test_laplace(self):
        # p = (30+1)/(40+2) = 31/42
        self.assertAlmostEqual(habit_rate(30, 40), 31 / 42)

    def test_zero_attended(self):
        # p = 1/2 with H=0 (Laplace floor)
        self.assertAlmostEqual(habit_rate(0, 0), 1 / 2)

    def test_all_attended(self):
        # p = (H+1)/(H+2) < 1 always
        p = habit_rate(40, 40)
        self.assertLess(p, 1.0)
        self.assertGreater(p, 0.9)


class TestProbabilityFinishSafe(unittest.TestCase):
    def test_must_zero_is_certain(self):
        """must_attend <= 0 -> probability = 1.0."""
        self.assertEqual(probability_finish_safe(20, 0, 0.75), 1.0)
        self.assertEqual(probability_finish_safe(20, -5, 0.75), 1.0)

    def test_must_exceeds_r_is_zero(self):
        """must_attend > R -> probability = 0.0."""
        self.assertEqual(probability_finish_safe(5, 10, 0.75), 0.0)

    def test_probability_decreases_as_must_increases(self):
        p = 0.75
        probs = [probability_finish_safe(20, m, p) for m in range(1, 21)]
        for i in range(len(probs) - 1):
            self.assertGreaterEqual(probs[i], probs[i + 1])

    def test_intermediate_value(self):
        prob = probability_finish_safe(20, 15, 0.75)
        self.assertGreater(prob, 0.0)
        self.assertLess(prob, 1.0)


class TestRiskLabel(unittest.TestCase):
    def test_low(self):
        self.assertEqual(risk_label(0.85), "Low")
        self.assertEqual(risk_label(0.80), "Low")

    def test_medium(self):
        self.assertEqual(risk_label(0.79), "Medium")
        self.assertEqual(risk_label(0.50), "Medium")

    def test_high(self):
        self.assertEqual(risk_label(0.49), "High")
        self.assertEqual(risk_label(0.0), "High")


class TestMonteCarloDistribution(unittest.TestCase):
    def test_returns_correct_keys(self):
        mc = monte_carlo_distribution(40, 30, 60)
        self.assertIn("mc_histogram", mc)
        self.assertIn("mc_bins", mc)

    def test_histogram_sums_to_runs(self):
        mc = monte_carlo_distribution(40, 30, 60, runs=5000, seed=42)
        self.assertEqual(sum(mc["mc_histogram"]), 5000)

    def test_reproducible_with_seed(self):
        mc1 = monte_carlo_distribution(40, 30, 60, runs=5000, seed=42)
        mc2 = monte_carlo_distribution(40, 30, 60, runs=5000, seed=42)
        self.assertEqual(mc1["mc_histogram"], mc2["mc_histogram"])


    def test_different_seed_gives_different_result(self):
        """Different seeds should give different histograms."""
        mc1 = monte_carlo_distribution(40, 30, 60, runs=5000, seed=42)
        mc2 = monte_carlo_distribution(40, 30, 60, runs=5000, seed=99)
        self.assertNotEqual(mc1["mc_histogram"], mc2["mc_histogram"])

    def test_simulated_mean_close_to_analytic(self):
        """Simulated mean final pct must be within 1-ppt of the analytic expectation.

        Analytic: E[final_pct] = (A + R*p) / T * 100 where p = habit_rate(A, H).
        """
        from core.services.risk import habit_rate
        H, A, T = 40, 30, 60
        R = T - H
        p = habit_rate(A, H)
        analytic_mean = (A + R * p) / T * 100

        mc = monte_carlo_distribution(H, A, T, runs=5000, seed=42)
        bins = mc["mc_bins"]
        counts = mc["mc_histogram"]
        midpoints = [(bins[i] + bins[i + 1]) / 2 for i in range(len(counts))]
        simulated_mean = sum(m * c for m, c in zip(midpoints, counts)) / sum(counts)

        self.assertAlmostEqual(simulated_mean, analytic_mean, delta=1.0)

class TestComputeRisk(unittest.TestCase):
    def test_spec_example(self):
        """H=40, A=30, T=60, thr=75 -- integration test."""
        result = compute_risk(40, 30, 60, 75)
        self.assertIn("probability", result)
        self.assertIn("label", result)
        self.assertIn("mc_histogram", result)
        prob = result["probability"]
        self.assertGreater(prob, 0.0)
        self.assertLess(prob, 1.0)
