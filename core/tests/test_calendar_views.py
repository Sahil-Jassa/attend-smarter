from datetime import date
from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Calendar, CalendarDay, Subject, TimetableSlot, AttendanceSnapshot


class CalendarViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="student_ui@example.com",
            email="student_ui@example.com",
            password="password123",
        )
        self.client.login(username="student_ui@example.com", password="password123")

    def test_calendar_setup_get(self):
        resp = self.client.get(reverse("core:calendar_setup"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Academic Calendar & Timetable Setup")

    def test_calendar_setup_post_redirects_to_preview(self):
        data = {
            "start_date": "2026-08-03",
            "last_working_day": "2026-11-28",
            "weekends_off": "on",
            "mode": "weekday",
        }
        resp = self.client.post(reverse("core:calendar_setup"), data)
        self.assertRedirects(resp, reverse("core:calendar_preview"))

        # Verify session has draft
        draft = self.client.session.get("calendar_setup_draft")
        self.assertIsNotNone(draft)
        self.assertEqual(draft["start_date"], "2026-08-03")
        # National holidays should be prefilled (15 Aug, 2 Oct)
        labels = [h["label"] for h in draft["holidays"]]
        self.assertIn("Independence Day", labels)
        self.assertIn("Gandhi Jayanti", labels)

    def test_calendar_preview_displays_summary_and_month_breakdown(self):
        session = self.client.session
        session["calendar_setup_draft"] = {
            "start_date": "2026-08-03",
            "last_working_day": "2026-08-28",
            "weekends_off": True,
            "mode": "weekday",
            "holidays": [
                {"date": "2026-08-15", "label": "Independence Day"},
                {"date": "2026-08-12", "label": "Local Holiday"},
            ],
            "subjects": [
                {
                    "name": "Machine Learning",
                    "slots": [{"weekday_or_day_order": 0, "periods": 2}],
                }
            ],
        }
        session.save()

        resp = self.client.get(reverse("core:calendar_preview"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Total Working Days")
        self.assertContains(resp, "Machine Learning")
        self.assertContains(resp, "August 2026")

    def test_calendar_save_creates_models_and_computes_total(self):
        session = self.client.session
        session["calendar_setup_draft"] = {
            "start_date": "2026-08-03",
            "last_working_day": "2026-08-28",
            "weekends_off": True,
            "mode": "weekday",
            "holidays": [
                {"date": "2026-08-12", "label": "College Fest"},
            ],
            "subjects": [
                {
                    "name": "Database Systems",
                    "slots": [
                        {"weekday_or_day_order": 0, "periods": 1},  # 4 Mondays
                        {"weekday_or_day_order": 2, "periods": 2},  # 3 working Wednesdays * 2 = 6
                    ],
                }
            ],
        }
        session.save()

        # Save action
        resp = self.client.post(reverse("core:calendar_save"), {})
        self.assertRedirects(resp, reverse("core:dashboard"))

        # Verify DB records
        cal = Calendar.objects.filter(user=self.user).first()
        self.assertIsNotNone(cal)
        self.assertEqual(cal.days.count(), 1)

        subj = Subject.objects.filter(user=self.user, name="Database Systems").first()
        self.assertIsNotNone(subj)
        self.assertEqual(subj.slots.count(), 2)
        # 4 + 6 = 10 total periods planned
        self.assertEqual(subj.total_planned, 10)

    def test_attendance_update_with_absences_and_auto_held(self):
        # Create calendar & subject with slots
        cal = Calendar.objects.create(
            user=self.user,
            start_date=date(2026, 8, 3),
            last_working_day=date(2026, 8, 28),
            weekends_off=True,
            mode="weekday",
        )
        subj = Subject.objects.create(
            user=self.user,
            name="Computer Networks",
            total_planned=10,
        )
        TimetableSlot.objects.create(subject=subj, weekday=0, periods=1)  # Mon
        TimetableSlot.objects.create(subject=subj, weekday=2, periods=2)  # Wed

        # Snapshot add via absences mode: held=auto (e.g. 5 held), absences=1 => attended = 4
        with patch("core.services.calendar_count.get_ist_today", return_value=date(2026, 8, 19)):
            # On 19 Aug: Week 1 Mon(1)+Wed(2)=3; Week 2 Mon(1)+Wed(2)=3; Aug 17 Mon(1) = 7 held
            resp = self.client.post(
                reverse("core:snapshot_add", kwargs={"pk": subj.pk}),
                {
                    "entry_mode": "absences",
                    "absences": 2,
                },
            )
            self.assertRedirects(resp, reverse("core:subject_detail", kwargs={"pk": subj.pk}))

            latest_snap = subj.snapshots.order_by("-recorded_at").first()
            self.assertIsNotNone(latest_snap)
            self.assertEqual(latest_snap.held, 7)
            self.assertEqual(latest_snap.attended, 5)  # 7 - 2 = 5

    def test_dashboard_safe_skip_days_card_and_medical_toggle(self):
        cal = Calendar.objects.create(
            user=self.user,
            start_date=date(2026, 8, 3),
            last_working_day=date(2026, 8, 28),
            weekends_off=True,
            mode="weekday",
        )
        subj = Subject.objects.create(
            user=self.user,
            name="Operating Systems",
            total_planned=20,
        )
        TimetableSlot.objects.create(subject=subj, weekday=4, periods=1)  # Fri

        with patch("core.views.get_ist_today", return_value=date(2026, 8, 3)), patch("core.services.calendar_count.get_ist_today", return_value=date(2026, 8, 3)):
            # 1. Normal mode (75%)
            resp = self.client.get(reverse("core:dashboard"))
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "Safe Skip Days")
            self.assertContains(resp, "75% Target")
            self.assertContains(resp, "Operating Systems")

            # 2. Toggle to Medical mode (65%)
            self.client.post(reverse("core:toggle_medical"))
            resp_med = self.client.get(reverse("core:dashboard"))
            self.assertEqual(resp_med.status_code, 200)
            self.assertContains(resp_med, "65% Target")

    def test_subject_detail_safe_skip_plan(self):
        cal = Calendar.objects.create(
            user=self.user,
            start_date=date(2026, 8, 3),
            last_working_day=date(2026, 8, 28),
            weekends_off=True,
            mode="weekday",
        )
        subj = Subject.objects.create(
            user=self.user,
            name="Algorithms",
            total_planned=16,
        )
        TimetableSlot.objects.create(subject=subj, weekday=2, periods=1)  # Wed
        TimetableSlot.objects.create(subject=subj, weekday=4, periods=1)  # Fri

        with patch("core.views.get_ist_today", return_value=date(2026, 8, 3)), patch("core.services.calendar_count.get_ist_today", return_value=date(2026, 8, 3)):
            resp = self.client.get(reverse("core:subject_detail", kwargs={"pk": subj.pk}))
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "Safe Skip Plan")
            self.assertContains(resp, "available skips")
            self.assertContains(resp, "Show full plan")
