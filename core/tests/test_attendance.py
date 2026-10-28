"""Unit tests for core/services/attendance.py.

All expected values come directly from the spec.
"""
import unittest

from core.services.attendance import (
    attendance_status,
    compute_all,
    current_percentage,
    must_attend,
    precompute_slider,
    remaining,
    required_total,
    safe_skips,
    what_if,
)


class TestRequiredTotal(unittest.TestCase):
    def test_spec_example(self):
        """H=40, A=30, T=60, thr=75 -> required_total=45."""
        self.assertEqual(required_total(60, 75), 45)

    def test_medical_threshold(self):
        self.assertEqual(required_total(60, 65), 39)

    def test_ceiling_applied(self):
        # 61 * 75 = 4575 / 100 = 45.75 -> ceil = 46
        self.assertEqual(required_total(61, 75), 46)

    def test_exact_multiple(self):
        # 100 * 75 / 100 = 75.0 exact
        self.assertEqual(required_total(100, 75), 75)


class TestMustAttendAndSafeSkips(unittest.TestCase):
    def test_spec_example(self):
        """H=40, A=30, T=60, thr=75 -> must_attend=15, R=20, safe_skips=5."""
        T, H, A, thr = 60, 40, 30, 75
        R = remaining(T, H)
        self.assertEqual(R, 20)
        req = required_total(T, thr)
        self.assertEqual(req, 45)
        must = must_attend(A, req)
        self.assertEqual(must, 15)
        self.assertEqual(safe_skips(R, must), 5)

    def test_must_never_negative(self):
        self.assertEqual(must_attend(45, 45), 0)
        self.assertEqual(must_attend(50, 45), 0)

    def test_safe_skips_never_negative(self):
        # must > R -> detention, skips = 0
        self.assertEqual(safe_skips(5, 10), 0)

    def test_h_equals_zero(self):
        result = compute_all(0, 0, 60, 75)
        self.assertIsNone(result["current_pct"])
        self.assertEqual(result["status"], "no_classes")

    def test_a_equals_h(self):
        result = compute_all(40, 40, 60, 75)
        self.assertAlmostEqual(result["current_pct"], 100.0)

    def test_a_equals_zero(self):
        result = compute_all(40, 0, 60, 75)
        self.assertAlmostEqual(result["current_pct"], 0.0)


class TestStatus(unittest.TestCase):
    def test_safe_status(self):
        """H=40, A=30, T=60 -- skips=5 > 2 and pct=75 >= threshold."""
        self.assertEqual(attendance_status(40, 30, 60, 75), "safe")

    def test_detention_zone(self):
        """A=30, H=55, T=60 -> R=5, must=15 > 5 -> detention_zone."""
        self.assertEqual(attendance_status(55, 30, 60, 75), "detention_zone")

    def test_warning_few_skips(self):
        # A=44, H=58, T=60: R=2, req=45, must=1, skips=1 (<=2) -> warning
        self.assertEqual(attendance_status(58, 44, 60, 75), "warning")

    def test_warning_below_threshold_pct(self):
        # H=20, A=12, T=60: pct=60 < 75 but recoverable
        self.assertEqual(attendance_status(20, 12, 60, 75), "warning")

    def test_threshold_toggle(self):
        """Same subject gives different results at 65 vs 75."""
        # H=40, A=26, T=60
        # thr=75: req=45, must=19, R=20, skips=1 -> warning
        # thr=65: req=39, must=13, R=20, skips=7 > 2, pct=65.0 == threshold -> safe
        status_75 = attendance_status(40, 26, 60, 75)
        status_65 = attendance_status(40, 26, 60, 65)
        self.assertNotEqual(status_75, status_65)
        self.assertEqual(status_65, "safe")

    def test_three_quarters_at_threshold_75_is_not_below(self):
        """H=4, A=3, T=20, thr=75 -> 3*100 < 75*4 is False (not below threshold)."""
        self.assertEqual(attendance_status(4, 3, 20, 75), "safe")


class TestWhatIf(unittest.TestCase):
    def test_zero_extra_skips(self):
        r = what_if(40, 30, 60, 75, 0)
        # projected_pct = 30/40*100 = 75.0
        self.assertAlmostEqual(r["projected_pct"], 75.0)
        # best_possible = (30+20)/60*100 = 83.333...
        self.assertAlmostEqual(r["best_possible_pct"], 83.333, places=2)

    def test_max_skip(self):
        r = what_if(40, 30, 60, 75, 20)  # skip all 20 remaining
        # projected_pct = 30/60*100 = 50.0
        self.assertAlmostEqual(r["projected_pct"], 50.0)
        # best_possible = (30+0)/60*100 = 50.0
        self.assertAlmostEqual(r["best_possible_pct"], 50.0)

    def test_clamped_beyond_r(self):
        r1 = what_if(40, 30, 60, 75, 20)
        r2 = what_if(40, 30, 60, 75, 999)
        self.assertAlmostEqual(r1["projected_pct"], r2["projected_pct"])


class TestPrecomputeSlider(unittest.TestCase):
    def test_length(self):
        # R=20 -> 21 entries (k=0..20)
        results = precompute_slider(40, 30, 60, 75)
        self.assertEqual(len(results), 21)

    def test_first_entry(self):
        results = precompute_slider(40, 30, 60, 75)
        self.assertEqual(results[0]["k"], 0)
        self.assertAlmostEqual(results[0]["projected_pct"], 75.0)
