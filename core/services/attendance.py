"""Pure-Python attendance calculation service.

All functions accept plain integers (no Django imports).
Uses integer arithmetic only to avoid float rounding bugs.
"""

from typing import Literal

StatusType = Literal["safe", "warning", "detention_zone", "no_classes"]


def _ceil_div(numerator: int, denominator: int) -> int:
    """Integer ceiling division: -(-a // b). No floats."""
    return -(-numerator // denominator)


# ---------------------------------------------------------------------------
# Core calculations
# ---------------------------------------------------------------------------

def required_total(total_planned: int, threshold: int) -> int:
    """Return ceil(threshold * total_planned / 100) using integer arithmetic.

    Formula: -(-thr * T // 100)

    >>> required_total(60, 75)
    45
    """
    return _ceil_div(threshold * total_planned, 100)


def remaining(total_planned: int, held: int) -> int:
    """Return R = T - H (classes not yet held)."""
    return total_planned - held


def current_percentage(held: int, attended: int):
    """Return current attendance percentage, or None if H = 0."""
    if held == 0:
        return None
    return attended / held * 100


def must_attend(attended: int, req_total: int) -> int:
    """Return max(0, required_total - attended)."""
    return max(0, req_total - attended)


def safe_skips(r: int, must: int) -> int:
    """Return max(0, R - must_attend)."""
    return max(0, r - must)


def max_possible_pct(attended: int, r: int, total_planned: int) -> float:
    """Return (A + R) / T * 100 -- the best possible final percentage."""
    return (attended + r) / total_planned * 100


def attendance_status(
    held: int,
    attended: int,
    total_planned: int,
    threshold: int,
) -> StatusType:
    """Classify the current attendance status.

    Returns one of: "no_classes", "safe", "warning", "detention_zone".
    """
    if held == 0:
        return "no_classes"

    r = remaining(total_planned, held)
    req = required_total(total_planned, threshold)
    must = must_attend(attended, req)
    skips = safe_skips(r, must)
    cur_pct = current_percentage(held, attended)

    if must > r:
        return "detention_zone"
    if skips <= 2 or (attended * 100 < threshold * held):
        return "warning"
    return "safe"


def compute_all(
    held: int,
    attended: int,
    total_planned: int,
    threshold: int,
) -> dict:
    """Return a dict with every attendance metric for a subject.

    Args:
        held:          H -- classes held so far.
        attended:      A -- classes attended so far.
        total_planned: T -- total planned classes in the semester.
        threshold:     Active threshold (e.g. 75 or 65).

    Returns:
        Dict with keys: current_pct, req_total, must, r, skips,
        max_possible_pct, status.
    """
    r = remaining(total_planned, held)
    req = required_total(total_planned, threshold)
    must = must_attend(attended, req)
    skips = safe_skips(r, must)
    cur_pct = current_percentage(held, attended)
    max_pct = max_possible_pct(attended, r, total_planned)
    status = attendance_status(held, attended, total_planned, threshold)

    return {
        "current_pct": cur_pct,
        "req_total": req,
        "must": must,
        "r": r,
        "skips": skips,
        "max_possible_pct": max_pct,
        "status": status,
    }


# ---------------------------------------------------------------------------
# What-if slider
# ---------------------------------------------------------------------------

def what_if(
    held: int,
    attended: int,
    total_planned: int,
    threshold: int,
    extra_skips: int,
) -> dict:
    """Compute projected attendance if the student skips k more classes.

    Slider represents skipping k of the *remaining* classes:
      projected_pct     = A / (H + k) * 100
      best_possible_pct = (A + R - k) / T * 100

    Args:
        extra_skips: k -- number of additional classes to skip (0 <= k <= R).

    Returns:
        Dict with projected_pct, best_possible_pct, projected_status.
    """
    r = remaining(total_planned, held)
    k = min(extra_skips, r)  # clamp to remaining

    new_held = held + k
    projected_pct = (attended / new_held * 100) if new_held > 0 else None
    best_possible_pct = (attended + r - k) / total_planned * 100 if total_planned > 0 else None

    req = required_total(total_planned, threshold)
    must = must_attend(attended, req)
    new_skips = safe_skips(r - k, must)
    if must > (r - k):
        projected_status: StatusType = "detention_zone"
    elif new_skips <= 2 or (new_held > 0 and attended * 100 < threshold * new_held):
        projected_status = "warning"
    else:
        projected_status = "safe"

    return {
        "projected_pct": projected_pct,
        "best_possible_pct": best_possible_pct,
        "projected_status": projected_status,
    }


def precompute_slider(
    held: int,
    attended: int,
    total_planned: int,
    threshold: int,
) -> list:
    """Return what_if results for k = 0 .. R as a list.

    Serialise with json_script so JS only looks up values, never recalculates.
    """
    r = remaining(total_planned, held)
    return [
        {"k": k, **what_if(held, attended, total_planned, threshold, k)}
        for k in range(r + 1)
    ]
