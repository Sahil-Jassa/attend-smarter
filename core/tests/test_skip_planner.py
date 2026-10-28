from datetime import date
from django.test import TestCase

from core.services.skip_planner import safe_skip_days


class SkipPlannerServiceTests(TestCase):
    def test_subject_with_zero_budget_blocks_every_day_it_meets(self):
        # Mon 2026-08-03 to Fri 2026-08-07
        # Subj A meets on Mon (0) and Wed (2) with budget 0
        # Subj B meets every weekday (0, 1, 2, 3, 4) with budget 10
        subjects = [
            {"id": "A", "name": "Subject A", "slots": {0: 1, 2: 1}, "budget": 0},
            {"id": "B", "name": "Subject B", "slots": {0: 1, 1: 1, 2: 1, 3: 1, 4: 1}, "budget": 10},
        ]
        start = date(2026, 8, 3)
        end = date(2026, 8, 7)
        today = date(2026, 8, 3)

        res = safe_skip_days(today=today, end=end, start=start, subjects=subjects)
        feasible_dates = [d["date"] for d in res["feasible_days"]]

        # Mon (2026-08-03) and Wed (2026-08-05) have Subj A meeting, so budget 0 blocks them
        self.assertNotIn(date(2026, 8, 3), feasible_dates)
        self.assertNotIn(date(2026, 8, 5), feasible_dates)

        # Tue (2026-08-04), Thu (2026-08-06), Fri (2026-08-07) where Subj A does NOT meet are feasible
        self.assertIn(date(2026, 8, 4), feasible_dates)
        self.assertIn(date(2026, 8, 6), feasible_dates)
        self.assertIn(date(2026, 8, 7), feasible_dates)

    def test_day_feasible_only_when_all_budgets_cover_day_periods(self):
        # Thursday 2026-08-06 has 2 periods of Subj A
        start = date(2026, 8, 6)
        end = date(2026, 8, 6)
        today = date(2026, 8, 6)

        # With budget 1: cost 2 > 1 => NOT feasible
        subj_budget_1 = [{"id": "A", "name": "Subject A", "slots": {3: 2}, "budget": 1}]
        res1 = safe_skip_days(today=today, end=end, start=start, subjects=subj_budget_1)
        self.assertEqual(len(res1["feasible_days"]), 0)

        # With budget 2: cost 2 <= 2 => feasible
        subj_budget_2 = [{"id": "A", "name": "Subject A", "slots": {3: 2}, "budget": 2}]
        res2 = safe_skip_days(today=today, end=end, start=start, subjects=subj_budget_2)
        self.assertEqual(len(res2["feasible_days"]), 1)
        self.assertEqual(res2["feasible_days"][0]["date"], date(2026, 8, 6))

    def test_friday_next_to_weekend_outranks_midweek_day_with_equal_cost(self):
        # Mon 2026-08-03 to Fri 2026-08-07
        # Subj has 1 period on Wed (2026-08-05) and 1 period on Fri (2026-08-07)
        start = date(2026, 8, 3)
        end = date(2026, 8, 7)
        today = date(2026, 8, 3)
        subjects = [{"id": "A", "name": "Subject A", "slots": {2: 1, 4: 1}, "budget": 5}]

        res = safe_skip_days(today=today, end=end, start=start, subjects=subjects, weekends_off=True)
        feasible = res["feasible_days"]
        self.assertEqual(len(feasible), 2)

        # Friday (bridge_score 1, adjacent to weekend) outranks Wednesday (bridge_score 0)
        self.assertEqual(feasible[0]["date"], date(2026, 8, 7))
        self.assertEqual(feasible[0]["weekday_name"], "Friday")
        self.assertEqual(feasible[0]["label"], "Long weekend")
        self.assertEqual(feasible[1]["date"], date(2026, 8, 5))
        self.assertEqual(feasible[1]["weekday_name"], "Wednesday")

    def test_holiday_is_never_suggested(self):
        # Mon 2026-08-03 to Fri 2026-08-07
        # Friday 2026-08-07 is a holiday
        start = date(2026, 8, 3)
        end = date(2026, 8, 7)
        today = date(2026, 8, 3)
        holiday = date(2026, 8, 7)
        subjects = [{"id": "A", "name": "Subject A", "slots": {i: 1 for i in range(5)}, "budget": 5}]

        res = safe_skip_days(today=today, end=end, start=start, holidays=[holiday], subjects=subjects)
        feasible_dates = [d["date"] for d in res["feasible_days"]]
        plan_dates = [d["date"] for d in res["plan"]]

        self.assertNotIn(holiday, feasible_dates)
        self.assertNotIn(holiday, plan_dates)

    def test_past_dates_and_today_rules_match_held_counting(self):
        # Mon 2026-08-03 to Fri 2026-08-07
        # Today is Wednesday 2026-08-05
        start = date(2026, 8, 3)
        end = date(2026, 8, 7)
        today = date(2026, 8, 5)
        subjects = [{"id": "A", "name": "Subject A", "slots": {i: 1 for i in range(5)}, "budget": 5}]

        res = safe_skip_days(today=today, end=end, start=start, subjects=subjects)
        feasible_dates = [d["date"] for d in res["feasible_days"]]

        # Held counting in calendar_count.py counts strictly before today:
        # Mon and Tue are held/past, so candidates are >= today (Wed, Thu, Fri)
        self.assertNotIn(date(2026, 8, 3), feasible_dates)
        self.assertNotIn(date(2026, 8, 4), feasible_dates)
        self.assertIn(date(2026, 8, 5), feasible_dates)
        self.assertIn(date(2026, 8, 6), feasible_dates)
        self.assertIn(date(2026, 8, 7), feasible_dates)

    def test_greedy_plan_never_overspends_budget(self):
        # 3 weeks with 3 subjects having limited budgets
        start = date(2026, 8, 3)
        end = date(2026, 8, 21)
        today = date(2026, 8, 3)

        subjects = [
            {"id": "A", "name": "Subject A", "slots": {0: 1, 1: 1, 2: 1, 3: 1, 4: 1}, "budget": 2},
            {"id": "B", "name": "Subject B", "slots": {0: 2, 2: 2, 4: 2}, "budget": 3},
            {"id": "C", "name": "Subject C", "slots": {1: 1, 3: 1}, "budget": 1},
        ]

        res = safe_skip_days(today=today, end=end, start=start, subjects=subjects)
        plan = res["plan"]
        budget_left = res["budget_left"]

        # 1. Budget left never negative
        for s_id, rem in budget_left.items():
            self.assertGreaterEqual(rem, 0)

        # 2. Total periods consumed per subject matches initial - left
        initial = res["initial_budgets"]
        for s in subjects:
            s_id = s["id"]
            spent = sum(d["costs"].get(s_id, 0) for d in plan)
            self.assertEqual(initial[s_id] - budget_left[s_id], spent)
            self.assertLessEqual(spent, initial[s_id])

    def test_switching_75_to_65_gives_more_feasible_days(self):
        # 10 weeks of classes (50 classes planned per subject, 1 per weekday)
        start = date(2026, 8, 3)
        end = date(2026, 10, 9)
        today = date(2026, 8, 3)

        # Total 50 classes planned. Currently 0 held, 0 attended.
        # At 75%: req = 38 => must = 38 => skips = 50 - 38 = 12
        # At 65%: req = 33 => must = 33 => skips = 50 - 33 = 17
        # Suppose a subject has held=20, attended=15.
        # Total planned = 50, remaining R = 30.
        # At 75%: req = 38 => must = 38 - 15 = 23 => skips = 30 - 23 = 7
        # At 65%: req = 33 => must = 33 - 15 = 18 => skips = 30 - 18 = 12
        subjects_input = [
            {
                "id": "A",
                "name": "Subject A",
                "slots": {0: 1, 1: 1, 2: 1, 3: 1, 4: 1},
                "held": 20,
                "attended": 15,
                "total_planned": 50,
            }
        ]

        res_75 = safe_skip_days(today=today, end=end, start=start, subjects=subjects_input, threshold=75)
        res_65 = safe_skip_days(today=today, end=end, start=start, subjects=subjects_input, threshold=65)

        # 65% threshold provides higher skip budget and at least as many or more feasible days
        self.assertGreater(res_65["initial_budgets"]["A"], res_75["initial_budgets"]["A"])
        self.assertGreaterEqual(len(res_65["plan"]), len(res_75["plan"]))
