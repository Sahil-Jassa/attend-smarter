"""Pure skip planner service without Django dependencies.
Computes feasible safe-skip dates and greedy multi-day skip plans based on
subject timetable slots, remaining classes, and attendance skip budgets.
"""

from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from core.services.attendance import must_attend, remaining, required_total, safe_skips
from core.services.calendar_count import (
    is_non_working,
    iter_calendar_days,
    normalize_dates,
    normalize_holidays,
    normalize_slots,
)

WEEKDAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def _normalize_subjects(
    subjects: Optional[Iterable[Any]],
    threshold: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Normalize input subjects into a consistent structure with precomputed skip budgets."""
    if not subjects:
        return []

    normalized: List[Dict[str, Any]] = []
    for idx, s in enumerate(subjects):
        if isinstance(s, dict):
            s_id = s.get("id", s.get("pk", idx))
            name = s.get("name", f"Subject {idx + 1}")
            slots_raw = s.get("slots")
            budget_val = s.get("budget", s.get("skip_budget"))
            held = s.get("held", 0)
            attended = s.get("attended", 0)
            total = s.get("total_planned", s.get("total", 0))
            s_thr = s.get("threshold", threshold)
        else:
            s_id = getattr(s, "id", getattr(s, "pk", idx))
            name = getattr(s, "name", f"Subject {idx + 1}")
            slots_raw = getattr(s, "slots", None)
            budget_val = getattr(s, "budget", getattr(s, "skip_budget", None))
            held = getattr(s, "held", 0)
            attended = getattr(s, "attended", 0)
            total = getattr(s, "total_planned", getattr(s, "total", 0))
            s_thr = getattr(s, "threshold", threshold)

        slot_map = normalize_slots(slots_raw)

        if budget_val is not None:
            budget = int(budget_val)
        elif s_thr is not None and total > 0:
            r = remaining(total, held)
            req = required_total(total, s_thr)
            must = must_attend(attended, req)
            budget = safe_skips(r, must)
        else:
            budget = 0

        normalized.append({
            "id": s_id,
            "name": name,
            "slots": slot_map,
            "budget": max(0, budget),
        })

    return normalized


def compute_bridge_score(
    curr_date: date,
    holiday_set: Set[date],
    override_set: Set[date],
    weekends_off: bool,
) -> Tuple[int, str]:
    """Calculate bridge score (0, 1, or 2) and descriptive label for a candidate day.
    Bridge score measures adjacency to weekends or holidays:
    - 2: Sandwich day / extra-long weekend (both yesterday and tomorrow are off)
    - 1: Long weekend / bridge day (adjacent to weekend or holiday)
    - 0: Midweek day (regular working days on both sides)
    """
    prev_off = is_non_working(curr_date - timedelta(days=1), holiday_set, override_set, weekends_off)
    next_off = is_non_working(curr_date + timedelta(days=1), holiday_set, override_set, weekends_off)
    score = (1 if prev_off else 0) + (1 if next_off else 0)

    w = curr_date.weekday()
    if score >= 2:
        label = "Long weekend"
    elif score == 1:
        if (w == 4 and next_off) or (w == 0 and prev_off):
            label = "Long weekend"
        else:
            label = "Long weekend" if (prev_off or next_off) else "Bridge day"
    else:
        label = "Midweek"

    return score, label


def safe_skip_days(
    today: date,
    end: date,
    holidays: Optional[Iterable[Any]] = None,
    working_overrides: Optional[Iterable[Any]] = None,
    weekends_off: bool = True,
    subjects: Optional[Iterable[Any]] = None,
    start: Optional[date] = None,
    day_order_mode: bool = False,
    day_order_cycle: int = 5,
    initial_day_order: int = 1,
    custom_day_orders: Optional[Dict[date, int]] = None,
    threshold: Optional[int] = None,
) -> Dict[str, Any]:
    """Compute feasible safe-skip dates and greedy multi-day plan.
    - Candidates: working dates >= today up to last working day (end).
    - A day's cost = periods per subject that day.
    - Feasible only if every subject's cost <= its budget. Budget 0 blocks the day if it meets.
    - Ranked by: bridge-day score (higher is better), then fewest total periods,
      then largest remaining total budget, then date ascending.
    - Greedy plan: pick best feasible day, subtract costs from budgets, repeat.
    """
    cal_start = start if start is not None else today
    norm_subjects = _normalize_subjects(subjects, threshold=threshold)

    holiday_set = normalize_holidays(holidays)
    override_set = normalize_dates(working_overrides)

    initial_budgets: Dict[Any, int] = {s["id"]: s["budget"] for s in norm_subjects}
    subject_names: Dict[Any, str] = {s["id"]: s["name"] for s in norm_subjects}

    # Gather candidate working days >= today
    candidate_days: List[Dict[str, Any]] = []

    for day_info in iter_calendar_days(
        start=cal_start,
        end=end,
        holidays=holidays,
        working_overrides=working_overrides,
        weekends_off=weekends_off,
        day_order_mode=day_order_mode,
        day_order_cycle=day_order_cycle,
        initial_day_order=initial_day_order,
        custom_day_orders=custom_day_orders,
    ):
        curr_d: date = day_info["date"]

        # Only candidates >= today and currently working
        if curr_d < today or not day_info["is_working"]:
            continue

        key = day_info["day_order"] if day_order_mode else day_info["weekday"]

        costs: Dict[Any, int] = {}
        breakdown: List[Dict[str, Any]] = []
        for s in norm_subjects:
            p = s["slots"].get(key, 0)
            costs[s["id"]] = p
            if p > 0:
                breakdown.append({
                    "id": s["id"],
                    "name": s["name"],
                    "periods": p,
                })

        total_periods = sum(costs.values())
        if total_periods == 0:
            continue

        b_score, b_label = compute_bridge_score(curr_d, holiday_set, override_set, weekends_off)

        candidate_days.append({
            "date": curr_d,
            "date_str": curr_d.strftime("%d %b %Y"),
            "weekday": curr_d.weekday(),
            "weekday_name": WEEKDAY_NAMES[curr_d.weekday()],
            "bridge_score": b_score,
            "label": b_label,
            "total_periods": total_periods,
            "periods_skipped": total_periods,
            "costs": costs,
            "subject_breakdown": breakdown,
        })

    def is_feasible(day_entry: Dict[str, Any], budgets: Dict[Any, int]) -> bool:
        """A day is feasible iff cost <= budget for every subject."""
        for s in norm_subjects:
            c = day_entry["costs"].get(s["id"], 0)
            if c > budgets.get(s["id"], 0):
                return False
        return True

    def sort_key(day_entry: Dict[str, Any], budgets: Dict[Any, int]):
        """Rank key: -bridge_score, +total_periods, -remaining_total_budget, date."""
        rem_budget = sum(budgets.get(s["id"], 0) - day_entry["costs"].get(s["id"], 0) for s in norm_subjects)
        return (
            -day_entry["bridge_score"],
            day_entry["total_periods"],
            -rem_budget,
            day_entry["date"],
        )

    # 1. Initially feasible days (standalone feasibility using initial budgets)
    feasible_days = [d for d in candidate_days if is_feasible(d, initial_budgets)]
    feasible_days.sort(key=lambda d: sort_key(d, initial_budgets))

    # 2. Greedy plan: pick best feasible day, subtract costs, repeat
    greedy_budgets = dict(initial_budgets)
    remaining_pool = list(candidate_days)
    plan: List[Dict[str, Any]] = []

    while True:
        pool_feasible = [d for d in remaining_pool if is_feasible(d, greedy_budgets)]
        if not pool_feasible:
            break

        pool_feasible.sort(key=lambda d: sort_key(d, greedy_budgets))
        best_day = pool_feasible[0]

        # Deduct costs
        for s in norm_subjects:
            greedy_budgets[s["id"]] -= best_day["costs"].get(s["id"], 0)

        plan.append(best_day)
        remaining_pool.remove(best_day)

    budget_left_named = {
        subject_names.get(s_id, str(s_id)): rem
        for s_id, rem in greedy_budgets.items()
    }

    return {
        "feasible_days": feasible_days,
        "plan": plan,
        "budget_left": greedy_budgets,
        "budget_left_named": budget_left_named,
        "initial_budgets": initial_budgets,
        "total_days_planned": len(plan),
        "total_periods_planned": sum(d["total_periods"] for d in plan),
    }
