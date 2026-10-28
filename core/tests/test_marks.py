"""Unit tests for core/services/marks.py.

All expected values come directly from the spec.
"""
import unittest
from fractions import Fraction

from core.services.marks import (
    external_needed,
    fail_warning,
    final_total,
    grade_table,
    round_half_up,
)


class TestRoundHalfUp(unittest.TestCase):
    def test_half_rounds_up(self):
        """0.5 -> 1, 50.5 -> 51."""
        self.assertEqual(round_half_up(Fraction(1, 2)), 1)
        self.assertEqual(round_half_up(Fraction(101, 2)), 51)  # 50.5 -> 51

    def test_whole_number_unchanged(self):
        self.assertEqual(round_half_up(Fraction(49)), 49)
        self.assertEqual(round_half_up(Fraction(50)), 50)

    def test_below_half_rounds_down(self):
        # 4.9 -> 5
        self.assertEqual(round_half_up(Fraction(49, 10)), 5)


class TestFinalTotal(unittest.TestCase):
    def test_3_external_with_48_internal(self):
        """3 marks -> 48 + 1.6 = 49.6 -> rounds to 50 (pass)."""
        self.assertEqual(final_total(48, 3), 50)

    def test_2_external_with_48_internal(self):
        """2 marks -> 48 + 1.067 = 49.07 -> rounds to 49 (fail)."""
        self.assertEqual(final_total(48, 2), 49)

    def test_perfect_external(self):
        """48 internal + 75 external -> 48 + 40 = 88."""
        self.assertEqual(final_total(48, 75), 88)

    def test_zero_external(self):
        self.assertEqual(final_total(48, 0), 48)

    def test_50_5_rounds_to_51(self):
        """50.5 must become 51 (round-half-up, not banker's rounding)."""
        self.assertEqual(round_half_up(Fraction(101, 2)), 51)


class TestExternalNeeded(unittest.TestCase):
    """Spec: internal = 48.

    O not possible, A+ needs 61, A needs 43, B+ needs 24, B needs 5, Pass needs 3.
    """

    def test_O_not_possible(self):
        # O min=91: ceil((182-1-96)*15/16)=ceil(85*15/16)=ceil(79.6875)=80 > 75
        self.assertGreater(external_needed(48, 91), 75)

    def test_A_plus_needs_61(self):
        # A+ min=81: ceil((162-1-96)*15/16)=ceil(65*15/16)=ceil(60.9375)=61
        self.assertEqual(external_needed(48, 81), 61)

    def test_A_needs_43(self):
        # A min=71: ceil((142-1-96)*15/16)=ceil(45*15/16)=ceil(42.1875)=43
        self.assertEqual(external_needed(48, 71), 43)

    def test_B_plus_needs_24(self):
        # B+ min=61: ceil((122-1-96)*15/16)=ceil(25*15/16)=ceil(23.4375)=24
        self.assertEqual(external_needed(48, 61), 24)

    def test_B_needs_5(self):
        # B min=51: ceil((102-1-96)*15/16)=ceil(5*15/16)=ceil(4.6875)=5
        self.assertEqual(external_needed(48, 51), 5)

    def test_pass_needs_3(self):
        # Pass min=50: ceil((100-1-96)*15/16)=ceil(3*15/16)=ceil(2.8125)=3
        self.assertEqual(external_needed(48, 50), 3)


class TestFailWarning(unittest.TestCase):
    def test_internal_9_fail_warning(self):
        """internal=9 -> final_total(9, 75) < 50 -> True."""
        self.assertTrue(fail_warning(9))

    def test_internal_10_no_fail_warning(self):
        """internal=10 -> final_total(10, 75) = 50 -> False."""
        self.assertFalse(fail_warning(10))

    def test_internal_50_no_fail_warning(self):
        """internal >= 50 -> pass already secured."""
        self.assertFalse(fail_warning(50))


class TestGradeTable(unittest.TestCase):
    def test_internal_48_rows(self):
        result = grade_table(48)
        rows = {r["grade"]: r for r in result["rows"]}
        self.assertEqual(rows["O"]["status"], "not_possible")
        self.assertEqual(rows["A+"]["status"], "reachable")
        self.assertEqual(rows["A+"]["needed_external"], 61)
        self.assertEqual(rows["A"]["needed_external"], 43)
        self.assertEqual(rows["B+"]["needed_external"], 24)
        self.assertEqual(rows["B"]["needed_external"], 5)
        self.assertEqual(rows["Pass"]["needed_external"], 3)

    def test_fail_warning_false_for_48(self):
        self.assertFalse(grade_table(48)["fail_warning"])

    def test_fail_warning_true_for_9(self):
        self.assertTrue(grade_table(9)["fail_warning"])

    def test_internal_50_pass_secured(self):
        result = grade_table(50)
        rows = {r["grade"]: r for r in result["rows"]}
        # Pass min=50: needed = ceil((100-1-100)*15/16) = ceil(-15/16) = 0 -> secured
        self.assertEqual(rows["Pass"]["status"], "secured")
        # B min=51: needed = ceil((102-1-100)*15/16) = ceil(15/16) = 1 -> reachable (needs 1 external)
        self.assertEqual(rows["B"]["status"], "reachable")
        self.assertEqual(rows["B"]["needed_external"], 1)


    def test_highlighted_grade_set(self):
        result = grade_table(48)
        self.assertEqual(result["highlighted"], "A")

    def test_highlighted_grade_fallback_when_none_under_60(self):
        # internal=10: Pass needs 75 (0 < needed <= 75, but > 60), all others > 75
        result = grade_table(10)
        self.assertEqual(result["highlighted"], "Pass")

    def test_no_fail_warning_internal_10(self):
        self.assertFalse(grade_table(10)["fail_warning"])
