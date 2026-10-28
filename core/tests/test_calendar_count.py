from datetime import date
from django.test import TestCase

from core.services.calendar_count import (
    count_classes,
    get_national_holidays,
)


class CalendarCountServiceTests(TestCase):
    def test_weekend_skipping(self):
        # Mon 2026-08-03 to Sun 2026-08-09 (7 days)
        # Weekday slots: Mon=1, Tue=1, Wed=1, Thu=1, Fri=1, Sat=1, Sun=1
        slots = {i: 1 for i in range(7)}
        start = date(2026, 8, 3)
        end = date(2026, 8, 9)
        today = date(2026, 8, 10)

        # With weekends_off=True, Sat & Sun must be skipped: 5 periods
        res = count_classes(start, end, today, holidays=[], working_overrides=[], weekends_off=True, slots=slots)
        self.assertEqual(res["total"], 5)
        self.assertEqual(res["held"], 5)

        # With weekends_off=False: 7 periods
        res_all = count_classes(start, end, today, holidays=[], working_overrides=[], weekends_off=False, slots=slots)
        self.assertEqual(res_all["total"], 7)
        self.assertEqual(res_all["held"], 7)

    def test_holiday_on_weekend_counted_once(self):
        # Mon 2026-08-03 to Sun 2026-08-09. Sat is 2026-08-08.
        slots = {i: 1 for i in range(7)}
        start = date(2026, 8, 3)
        end = date(2026, 8, 9)
        today = date(2026, 8, 10)
        # Sat 2026-08-08 is listed as holiday
        holidays = [date(2026, 8, 8)]

        res = count_classes(start, end, today, holidays=holidays, working_overrides=[], weekends_off=True, slots=slots)
        # Total should still be 5, not 5 - 1 = 4
        self.assertEqual(res["total"], 5)
        self.assertEqual(res["held"], 5)

    def test_working_saturday_override(self):
        # Mon 2026-08-03 to Sun 2026-08-09.
        # Sat 2026-08-08 is in working_overrides.
        slots = {i: 1 for i in range(7)}
        start = date(2026, 8, 3)
        end = date(2026, 8, 9)
        today = date(2026, 8, 10)
        overrides = [date(2026, 8, 8)]

        res = count_classes(start, end, today, holidays=[], working_overrides=overrides, weekends_off=True, slots=slots)
        # 5 weekdays + 1 Saturday override = 6
        self.assertEqual(res["total"], 6)
        self.assertEqual(res["held"], 6)

    def test_inclusive_start_and_end(self):
        # Start and end are both single days (same date: Wed 2026-08-05)
        slots = {2: 3}  # Wednesday has 3 periods
        d = date(2026, 8, 5)

        # Today is before d: total=3, held=0
        res1 = count_classes(d, d, today=date(2026, 8, 4), holidays=[], working_overrides=[], weekends_off=True, slots=slots)
        self.assertEqual(res1["total"], 3)
        self.assertEqual(res1["held"], 0)

        # Today is after d: total=3, held=3
        res2 = count_classes(d, d, today=date(2026, 8, 6), holidays=[], working_overrides=[], weekends_off=True, slots=slots)
        self.assertEqual(res2["total"], 3)
        self.assertEqual(res2["held"], 3)

    def test_lab_slot_2_periods(self):
        # Tuesday has lab of 2 periods
        slots = {1: 2}  # Tue=2
        start = date(2026, 8, 4)  # Tuesday
        end = date(2026, 8, 11)    # Next Tuesday
        today = date(2026, 8, 12)

        res = count_classes(start, end, today, holidays=[], working_overrides=[], weekends_off=True, slots=slots)
        # Two Tuesdays * 2 periods = 4
        self.assertEqual(res["total"], 4)
        self.assertEqual(res["held"], 4)

    def test_day_order_mode(self):
        # Day order mode: working dates map to Day Order 1..5.
        # Week 1: Mon(DO1), Tue(DO2), Wed(Holiday), Thu(DO3), Fri(DO4)
        # Week 2: Mon(DO5), Tue(DO1)
        # Slots keyed by day order: DO1 has 2 periods, DO3 has 1 period.
        slots = {1: 2, 3: 1}
        start = date(2026, 8, 3)   # Mon
        end = date(2026, 8, 11)    # Tue of week 2
        holidays = [date(2026, 8, 5)]  # Wed
        today = date(2026, 8, 12)

        res = count_classes(
            start, end, today,
            holidays=holidays,
            working_overrides=[],
            weekends_off=True,
            slots=slots,
            day_order_mode=True
        )
        # Working days & day orders:
        # Mon Aug 3: DO 1 -> 2 periods
        # Tue Aug 4: DO 2 -> 0 periods
        # Wed Aug 5: Holiday (skipped)
        # Thu Aug 6: DO 3 -> 1 period
        # Fri Aug 7: DO 4 -> 0 periods
        # Sat/Sun: Weekend (skipped)
        # Mon Aug 10: DO 5 -> 0 periods
        # Tue Aug 11: DO 1 -> 2 periods
        # Total = 2 + 1 + 2 = 5
        self.assertEqual(res["total"], 5)
        self.assertEqual(res["held"], 5)

    def test_today_excluded_from_held(self):
        # Class on Wednesday 2026-08-05.
        slots = {2: 1}
        start = date(2026, 8, 3)
        end = date(2026, 8, 7)
        # If today IS Wednesday 2026-08-05, classes on today are strictly NOT held yet
        res = count_classes(start, end, today=date(2026, 8, 5), holidays=[], working_overrides=[], weekends_off=True, slots=slots)
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["held"], 0)

        # Once today moves to Thursday 2026-08-06, Wednesday's class is held
        res_next = count_classes(start, end, today=date(2026, 8, 6), holidays=[], working_overrides=[], weekends_off=True, slots=slots)
        self.assertEqual(res_next["total"], 1)
        self.assertEqual(res_next["held"], 1)

    def test_held_adjustment_applied(self):
        slots = {0: 1, 1: 1}
        start = date(2026, 8, 3)
        end = date(2026, 8, 7)
        today = date(2026, 8, 7)  # Mon and Tue have passed => 2 held

        # cancelled class: held_adjustment = -1
        res = count_classes(start, end, today, holidays=[], working_overrides=[], weekends_off=True, slots=slots, held_adjustment=-1)
        self.assertEqual(res["total"], 2)
        self.assertEqual(res["held"], 1)

        # extra class: held_adjustment = +2
        res2 = count_classes(start, end, today, holidays=[], working_overrides=[], weekends_off=True, slots=slots, held_adjustment=2)
        self.assertEqual(res2["total"], 2)
        self.assertEqual(res2["held"], 4)

    def test_hand_counted_four_week_example(self):
        # 4 weeks: Mon 2026-08-03 to Fri 2026-08-28 (20 regular weekdays)
        # Timetable for Subject:
        # Mon: 1, Tue: 1, Wed: 2 (lab), Thu: 1, Fri: 1, Sat: 0 => 6 periods / regular week
        # Overrides: Sat 2026-08-22 is a working Saturday with 1 period (slot[5] = 1)
        # Holidays:
        # - Sat 2026-08-15 (Independence Day, on a weekend)
        # - Wed 2026-08-12 (single holiday, 2 periods missed)
        # - Mon 2026-08-24 to Tue 2026-08-25 (range holiday e.g. study leave, 1+1=2 periods missed)
        # Today: Wed 2026-08-19 (midway)
        # Held adjustment: -1 (one lecture cancelled in week 1)
        slots = {0: 1, 1: 1, 2: 2, 3: 1, 4: 1, 5: 1}
        start = date(2026, 8, 3)
        end = date(2026, 8, 28)
        holidays = [
            date(2026, 8, 15),
            date(2026, 8, 12),
            (date(2026, 8, 24), date(2026, 8, 25)),
        ]
        overrides = [date(2026, 8, 22)]
        today = date(2026, 8, 19)

        # Hand calculations:
        # Week 1 (Aug 3 - Aug 7): Mon(1) + Tue(1) + Wed(2) + Thu(1) + Fri(1) = 6
        # Week 2 (Aug 10 - Aug 14): Mon(1) + Tue(1) + Wed(0, hol) + Thu(1) + Fri(1) = 4
        #   (Aug 15 is Sat holiday, already weekend off -> 0)
        # Week 3 (Aug 17 - Aug 21 + Sat Aug 22):
        #   Mon 17: 1
        #   Tue 18: 1
        #   Wed 19 (today! not in held): 2
        #   Thu 20: 1
        #   Fri 21: 1
        #   Sat 22 (working override): 1
        #   Week 3 total = 1+1+2+1+1+1 = 7.
        # Week 4 (Aug 24 - Aug 28):
        #   Mon 24: 0 (holiday range)
        #   Tue 25: 0 (holiday range)
        #   Wed 26: 2
        #   Thu 27: 1
        #   Fri 28: 1
        #   Week 4 total = 4.
        # Total across 4 weeks = 6 + 4 + 7 + 4 = 21.
        #
        # Classes strictly before today (Aug 19):
        # Week 1: 6
        # Week 2: 4
        # Aug 17: 1
        # Aug 18: 1
        # Subtotal held = 6 + 4 + 1 + 1 = 12.
        # With held_adjustment = -1: 12 - 1 = 11.

        res = count_classes(
            start, end, today,
            holidays=holidays,
            working_overrides=overrides,
            weekends_off=True,
            slots=slots,
            held_adjustment=-1,
        )
        self.assertEqual(res["total"], 21)
        self.assertEqual(res["held"], 11)

    def test_prefill_national_holidays(self):
        # 2026 span: Jan 1 2026 to Dec 31 2026
        holidays = get_national_holidays(date(2026, 1, 1), date(2026, 12, 31))
        dates = [h["date"] for h in holidays]
        self.assertIn(date(2026, 1, 26), dates)
        self.assertIn(date(2026, 8, 15), dates)
        self.assertIn(date(2026, 10, 2), dates)

        # Range outside 26 Jan:
        subset = get_national_holidays(date(2026, 8, 1), date(2026, 9, 1))
        self.assertEqual(len(subset), 1)
        self.assertEqual(subset[0]["date"], date(2026, 8, 15))


from django.contrib.auth.models import User
from core.models import Subject, Calendar, CalendarDay, TimetableSlot


class CalendarModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="teststudent@example.com", email="teststudent@example.com", password="password123")
        self.calendar = Calendar.objects.create(
            user=self.user,
            start_date=date(2026, 8, 3),
            last_working_day=date(2026, 8, 28),
            weekends_off=True,
            mode=Calendar.MODE_WEEKDAY,
        )
        self.subject = Subject.objects.create(
            user=self.user,
            name="Data Structures",
            total_planned=20,
            held_adjustment=-1,
        )

    def test_calendar_day_and_slot_model_integration(self):
        # Create timetable slots: Mon(1 period), Wed(2 periods)
        TimetableSlot.objects.create(subject=self.subject, weekday=0, periods=1)
        TimetableSlot.objects.create(subject=self.subject, weekday=2, periods=2)

        # Mark 12 Aug as holiday
        CalendarDay.objects.create(
            calendar=self.calendar,
            date=date(2026, 8, 12),
            kind=CalendarDay.KIND_HOLIDAY,
            label="College Fest",
        )

        # Compute attendance on 2026-08-19
        counts = self.subject.compute_attendance_counts(today=date(2026, 8, 19))
        self.assertIsNotNone(counts)
        # Total across 4 weeks: Mon(4*1 = 4) + Wed(3 working Wednesdays * 2 = 6) = 10 periods
        self.assertEqual(counts["total"], 10)
        # Held before 19 Aug: Week 1 Mon(1) + Wed(2) = 3; Week 2 Mon(1) + Wed(0) = 1; Week 3 Mon(1) = 1 => 5.
        # Adjusted with held_adjustment=-1 => 5 - 1 = 4.
        self.assertEqual(counts["held"], 4)

