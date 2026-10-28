"""Pure-Python marks and grade calculation service.

No Django imports.
Uses integer / Fraction arithmetic throughout; rounds ONCE at the very end
with round_half_up (floor(x + 0.5)), NOT Python built-in round()
(which uses banker's rounding).

Grade bands (minimum final total out of 100):
  O    = 91
  A+   = 81
  A    = 71
  B+   = 61
  B    = 51
  Pass = 50
  Fail = below 50
"""

from fractions import Fraction
from math import floor
from typing import Literal


# Grade definitions in descending order of difficulty.
GRADES: list = [
    ("O",    91),
    ("A+",   81),
    ("A",    71),
    ("B+",   61),
    ("B",    51),
    ("Pass", 50),
]

StatusStr = Literal["secured", "reachable", "not_possible"]


# ---------------------------------------------------------------------------
# Arithmetic helpers
# ---------------------------------------------------------------------------

def _ceil_int(numerator: int, denominator: int) -> int:
    """Integer ceiling division (no floats)."""
    return -(-numerator // denominator)


def round_half_up(x: Fraction) -> int:
    """Round a Fraction to the nearest integer, half-up (not banker's rounding).

    Equivalent to floor(x + 0.5).

    >>> round_half_up(Fraction(1, 2))
    1
    >>> round_half_up(Fraction(101, 2))
    51
    """
    return floor(x + Fraction(1, 2))


# ---------------------------------------------------------------------------
# Core marks calculations
# ---------------------------------------------------------------------------

def final_total(internal: int, external: int) -> int:
    """Compute the rounded final total out of 100.

    Conversion: external (out of 75) is scaled to 40.
    Formula:    round_half_up(internal + external * 40/75)
    Rounds ONCE at the end using Fraction arithmetic for exactness.
    """
    raw = Fraction(internal) + Fraction(external * 40, 75)
    return round_half_up(raw)


def external_needed(internal: int, target_min: int) -> int:
    """Compute minimum external marks (out of 75) needed for a target grade.

    Exact formula: ceil((2 * target_min - 1 - 2 * internal) * 15 / 16)
    Uses integer ceiling division -- no floats.

    Returns a value that may be <= 0 (secured) or > 75 (not possible).
    """
    numerator = (2 * target_min - 1 - 2 * internal) * 15
    return _ceil_int(numerator, 16)


def converted_display(external: int) -> str:
    """Return the exact converted value as 'X.X / 40' (1 decimal, no rounding stored)."""
    val = Fraction(external * 40, 75)
    return f"{float(val):.1f} / 40"


# ---------------------------------------------------------------------------
# Grade table
# ---------------------------------------------------------------------------

def fail_warning(internal: int) -> bool:
    """Return True if even a perfect external (75) cannot reach a pass (50).

    Occurs when internal <= 9:
      final_total(9, 75)  = round_half_up(9 + 40)  = 49 < 50  -> True
      final_total(10, 75) = round_half_up(10 + 40) = 50 >= 50 -> False
    """
    return final_total(internal, 75) < 50


def grade_table(internal: int) -> dict:
    """Compute the full grade table for a given internal score.

    Args:
        internal: Internal marks (0-60).

    Returns:
        dict with:
          rows         -- list of dicts, one per grade band
          highlighted  -- name of the highlighted (easiest reachable) grade
          fail_warning -- True if even a perfect external cannot give a pass
    """
    rows = []
    show_warning = fail_warning(internal)

    # Highlighted grade:
    # 1. Highest grade with 0 < needed <= 60 (e.g. internal 48 -> A)
    highlighted_grade = None
    for grade_name, min_total in GRADES:
        needed = external_needed(internal, min_total)
        if 0 < needed <= 60:
            highlighted_grade = grade_name
            break

    # 2. If none, easiest reachable grade (0 < needed <= 75)
    if highlighted_grade is None:
        for grade_name, min_total in reversed(GRADES):
            needed = external_needed(internal, min_total)
            if 0 < needed <= 75:
                highlighted_grade = grade_name
                break

    # 3. If every grade is already secured, highlight the highest secured
    if highlighted_grade is None:
        for grade_name, min_total in GRADES:
            if external_needed(internal, min_total) <= 0:
                highlighted_grade = grade_name
                break

    for grade_name, min_total in GRADES:
        needed = external_needed(internal, min_total)

        if needed <= 0:
            status: StatusStr = "secured"
            display = "Secured, even with 0 in the external"
            conv = None
        elif needed > 75:
            status = "not_possible"
            display = "Not possible"
            conv = None
        else:
            status = "reachable"
            display = f"{needed} / 75"
            conv = converted_display(needed)

        rows.append({
            "grade": grade_name,
            "min_total": min_total,
            "needed_external": needed if status == "reachable" else None,
            "status": status,
            "display": display,
            "converted_display": conv,
            "highlighted": (grade_name == highlighted_grade),
        })

    return {
        "rows": rows,
        "highlighted": highlighted_grade,
        "fail_warning": show_warning,
    }
