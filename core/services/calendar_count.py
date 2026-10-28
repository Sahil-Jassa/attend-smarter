"""Pure calendar counting service without Django dependencies.
Handles class schedule counting, holidays, weekend skipping, day-order mapping, and adjustments.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union

IST = timezone(timedelta(hours=5, minutes=30))


def get_ist_today() -> date:
    """Return today's date in Indian Standard Time (UTC+5:30)."""
    return datetime.now(IST).date()


def normalize_holidays(holidays: Optional[Iterable[Any]]) -> Set[date]:
    """Convert flexible holiday representations (single dates, date ranges, tuples, dicts) into a flat set of dates."""
    holiday_set: Set[date] = set()
    if not holidays:
        return holiday_set

    for item in holidays:
        if isinstance(item, date):
            holiday_set.add(item)
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            d_start, d_end = item
            if isinstance(d_start, date) and isinstance(d_end, date):
                curr = d_start
                while curr <= d_end:
                    holiday_set.add(curr)
                    curr += timedelta(days=1)
        elif isinstance(item, dict):
            if "start" in item and "end" in item:
                d_start = item["start"]
                d_end = item["end"]
                curr = d_start
                while curr <= d_end:
                    holiday_set.add(curr)
                    curr += timedelta(days=1)
            elif "date" in item and isinstance(item["date"], date):
                holiday_set.add(item["date"])
        elif hasattr(item, "date") and isinstance(getattr(item, "date"), date):
            holiday_set.add(getattr(item, "date"))

    return holiday_set


def normalize_dates(dates_input: Optional[Iterable[Any]]) -> Set[date]:
    """Convert an iterable of dates/dicts/objects into a set of dates."""
    date_set: Set[date] = set()
    if not dates_input:
        return date_set

    for item in dates_input:
        if isinstance(item, date):
            date_set.add(item)
        elif isinstance(item, dict) and "date" in item and isinstance(item["date"], date):
            date_set.add(item["date"])
        elif hasattr(item, "date") and isinstance(getattr(item, "date"), date):
            date_set.add(getattr(item, "date"))

    return date_set


def normalize_slots(slots: Any) -> Dict[int, int]:
    """Convert various slot formats into a dict of {weekday_or_day_order: periods}."""
    slot_dict: Dict[int, int] = {}
    if not slots:
        return slot_dict

    if isinstance(slots, dict):
        for k, v in slots.items():
            try:
                slot_dict[int(k)] = int(v)
            except (ValueError, TypeError):
                continue
        return slot_dict

    for item in slots:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            try:
                slot_dict[int(item[0])] = int(item[1])
            except (ValueError, TypeError):
                continue
        elif isinstance(item, dict):
            k = item.get("weekday") if item.get("weekday") is not None else item.get("day_order")
            p = item.get("periods", 1)
            if k is not None:
                try:
                    slot_dict[int(k)] = int(p)
                except (ValueError, TypeError):
                    continue
        elif hasattr(item, "periods"):
            k = getattr(item, "weekday", None)
            if k is None:
                k = getattr(item, "day_order", None)
            if k is not None:
                try:
                    slot_dict[int(k)] = int(getattr(item, "periods", 1))
                except (ValueError, TypeError):
                    continue

    return slot_dict


def get_national_holidays(start: date, end: date) -> List[Dict[str, Any]]:
    """Return fixed-date national holidays falling within the given range [start, end].
    Republic Day: 26 Jan
    Independence Day: 15 Aug
    Gandhi Jayanti: 02 Oct
    """
    fixed_holidays = [
        (1, 26, "Republic Day"),
        (8, 15, "Independence Day"),
        (10, 2, "Gandhi Jayanti"),
    ]
    results: List[Dict[str, Any]] = []
    for year in range(start.year, end.year + 1):
        for month, day, label in fixed_holidays:
            try:
                h_date = date(year, month, day)
                if start <= h_date <= end:
                    results.append({"date": h_date, "label": label})
            except ValueError:
                continue

    results.sort(key=lambda x: x["date"])
    return results


def is_non_working(
    target_date: date,
    holiday_set: Set[date],
    override_set: Set[date],
    weekends_off: bool = True,
) -> bool:
    """Return True if target_date is a non-working day (weekend without override, or holiday)."""
    w = target_date.weekday()
    is_weekend = w in (5, 6)
    is_override = target_date in override_set
    is_holiday = target_date in holiday_set
    if is_weekend:
        if weekends_off and not is_override:
            return True
        return is_holiday
    return is_holiday


def iter_calendar_days(
    start: date,
    end: date,
    holidays: Optional[Iterable[Any]] = None,
    working_overrides: Optional[Iterable[Any]] = None,
    weekends_off: bool = True,
    day_order_mode: bool = False,
    day_order_cycle: int = 5,
    initial_day_order: int = 1,
    custom_day_orders: Optional[Dict[date, int]] = None,
) -> Iterable[Dict[str, Any]]:
    """Iterate through all calendar days from start to end (inclusive) yielding day metadata."""
    holiday_set = normalize_holidays(holidays)
    override_set = normalize_dates(working_overrides)

    current_day_order = initial_day_order
    curr = start

    while curr <= end:
        w = curr.weekday()  # Mon=0 .. Sun=6
        is_weekend = w in (5, 6)
        is_override = curr in override_set
        is_holiday = curr in holiday_set

        # Determine if working
        if is_weekend:
            if weekends_off and not is_override:
                is_working = False
            else:
                is_working = not is_holiday
        else:
            is_working = not is_holiday

        day_order = None
        if is_working and day_order_mode:
            if custom_day_orders and curr in custom_day_orders:
                day_order = custom_day_orders[curr]
            else:
                day_order = current_day_order
                current_day_order = 1 if current_day_order >= day_order_cycle else current_day_order + 1

        yield {
            "date": curr,
            "is_working": is_working,
            "weekday": w,
            "day_order": day_order,
            "is_weekend": is_weekend,
            "is_holiday": is_holiday,
            "is_override": is_override,
        }
        curr += timedelta(days=1)


def iter_working_days(
    start: date,
    end: date,
    holidays: Optional[Iterable[Any]] = None,
    working_overrides: Optional[Iterable[Any]] = None,
    weekends_off: bool = True,
    day_order_mode: bool = False,
    day_order_cycle: int = 5,
    initial_day_order: int = 1,
    custom_day_orders: Optional[Dict[date, int]] = None,
) -> Iterable[Dict[str, Any]]:
    """Yield only working calendar days with their weekday or day order."""
    for day in iter_calendar_days(
        start=start,
        end=end,
        holidays=holidays,
        working_overrides=working_overrides,
        weekends_off=weekends_off,
        day_order_mode=day_order_mode,
        day_order_cycle=day_order_cycle,
        initial_day_order=initial_day_order,
        custom_day_orders=custom_day_orders,
    ):
        if day["is_working"]:
            yield day


def build_working_calendar(
    start: date,
    end: date,
    holidays: Optional[Iterable[Any]] = None,
    working_overrides: Optional[Iterable[Any]] = None,
    weekends_off: bool = True,
    day_order_mode: bool = False,
    day_order_cycle: int = 5,
    initial_day_order: int = 1,
    custom_day_orders: Optional[Dict[date, int]] = None,
) -> List[Dict[str, Any]]:
    """Build day-by-day calendar information between start and end (both inclusive).
    Returns list of dicts:
    [{
        'date': date,
        'is_working': bool,
        'weekday': int,
        'day_order': Optional[int],
        'is_weekend': bool,
        'is_holiday': bool,
        'is_override': bool
    }, ...]
    """
    return list(
        iter_calendar_days(
            start=start,
            end=end,
            holidays=holidays,
            working_overrides=working_overrides,
            weekends_off=weekends_off,
            day_order_mode=day_order_mode,
            day_order_cycle=day_order_cycle,
            initial_day_order=initial_day_order,
            custom_day_orders=custom_day_orders,
        )
    )


def count_classes(
    start: date,
    end: date,
    today: Optional[date] = None,
    holidays: Optional[Iterable[Any]] = None,
    working_overrides: Optional[Iterable[Any]] = None,
    weekends_off: bool = True,
    slots: Any = None,
    day_order_mode: bool = False,
    day_order_cycle: int = 5,
    initial_day_order: int = 1,
    custom_day_orders: Optional[Dict[date, int]] = None,
    held_adjustment: int = 0,
) -> Dict[str, int]:
    """Count total and held classes for given date range and slot schedule.
    - start and end are both inclusive.
    - weekends_off skips Saturdays and Sundays unless in working_overrides.
    - Holidays on weekends are counted once (never subtracted twice).
    - held counts periods strictly before today.
    - held_adjustment adjusts held (e.g. for cancelled classes).
    Returns: {'total': int, 'held': int}
    """
    if today is None:
        today = get_ist_today()

    slot_map = normalize_slots(slots)
    cal_days = build_working_calendar(
        start=start,
        end=end,
        holidays=holidays,
        working_overrides=working_overrides,
        weekends_off=weekends_off,
        day_order_mode=day_order_mode,
        day_order_cycle=day_order_cycle,
        initial_day_order=initial_day_order,
        custom_day_orders=custom_day_orders,
    )

    total_periods = 0
    held_periods = 0

    for day_info in cal_days:
        if not day_info["is_working"]:
            continue

        key = day_info["day_order"] if day_order_mode else day_info["weekday"]
        periods = slot_map.get(key, 0)
        total_periods += periods

        # "held = periods on dates strictly before today (today counts only after the day ends)"
        if day_info["date"] < today:
            held_periods += periods

    adjusted_held = max(0, held_periods + held_adjustment)

    return {
        "total": total_periods,
        "held": adjusted_held,
    }
