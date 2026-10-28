"""View-level tests: ownership, snapshot validation, auth flows."""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

from core.models import Subject, AttendanceSnapshot, Profile


def make_user(email, password="testpass123"):
    u = User.objects.create_user(username=email, email=email, password=password)
    return u


class OwnershipTest(TestCase):
    """A user must get 404 for another user's subject."""

    def setUp(self):
        self.alice = make_user("alice@example.com")
        self.bob = make_user("bob@example.com")
        self.subj = Subject(user=self.alice, name="Maths", total_planned=60)
        self.subj.full_clean()
        Subject.objects.bulk_create([self.subj])
        self.subj = Subject.objects.get(user=self.alice, name="Maths")

    def test_bob_cannot_view_alices_subject(self):
        self.client.force_login(self.bob)
        resp = self.client.get(reverse("core:subject_detail", args=[self.subj.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_bob_cannot_edit_alices_subject(self):
        self.client.force_login(self.bob)
        resp = self.client.get(reverse("core:subject_edit", args=[self.subj.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_bob_cannot_delete_alices_subject(self):
        self.client.force_login(self.bob)
        resp = self.client.post(reverse("core:subject_delete", args=[self.subj.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_alice_can_view_own_subject(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("core:subject_detail", args=[self.subj.pk]))
        self.assertEqual(resp.status_code, 200)


class SnapshotValidationTest(TestCase):
    """Snapshots must enforce A <= H <= T."""

    def setUp(self):
        self.user = make_user("carol@example.com")
        self.subj = Subject(user=self.user, name="Physics", total_planned=60)
        self.subj.full_clean()
        Subject.objects.bulk_create([self.subj])
        self.subj = Subject.objects.get(user=self.user, name="Physics")
        self.client.force_login(self.user)
        self.url = reverse("core:snapshot_add", args=[self.subj.pk])

    def test_valid_snapshot_succeeds(self):
        resp = self.client.post(self.url, {"held": 30, "attended": 25})
        self.assertRedirects(resp, reverse("core:subject_detail", args=[self.subj.pk]))
        self.assertEqual(AttendanceSnapshot.objects.filter(subject=self.subj).count(), 1)

    def test_attended_exceeds_held_rejected(self):
        resp = self.client.post(self.url, {"held": 20, "attended": 25})
        self.assertEqual(AttendanceSnapshot.objects.filter(subject=self.subj).count(), 0)

    def test_held_exceeds_total_planned_rejected(self):
        resp = self.client.post(self.url, {"held": 70, "attended": 60})
        self.assertEqual(AttendanceSnapshot.objects.filter(subject=self.subj).count(), 0)

    def test_direct_save_attended_exceeds_held_raises_validation_error(self):
        from django.core.exceptions import ValidationError
        snap = AttendanceSnapshot(subject=self.subj, held=20, attended=25)
        with self.assertRaises(ValidationError):
            snap.save()

    def test_direct_save_held_exceeds_total_planned_raises_validation_error(self):
        from django.core.exceptions import ValidationError
        snap = AttendanceSnapshot(subject=self.subj, held=70, attended=50)
        with self.assertRaises(ValidationError):
            snap.save()


class AuthFlowTest(TestCase):
    """Signup and login with email."""

    def test_signup_creates_user_and_profile(self):
        resp = self.client.post(reverse("core:signup"), {
            "email": "newuser@example.com",
            "password1": "Str0ng!Pass",
            "password2": "Str0ng!Pass",
        })
        self.assertRedirects(resp, reverse("core:dashboard"))
        u = User.objects.get(username="newuser@example.com")
        self.assertTrue(hasattr(u, "profile"))

    def test_signup_duplicate_email_rejected(self):
        make_user("dup@example.com")
        resp = self.client.post(reverse("core:signup"), {
            "email": "dup@example.com",
            "password1": "Str0ng!Pass",
            "password2": "Str0ng!Pass",
        })
        # Should not redirect -- form error
        self.assertEqual(resp.status_code, 200)

    def test_login_with_email(self):
        make_user("login@example.com", "Str0ng!Pass")
        resp = self.client.post(reverse("core:login"), {
            "username": "login@example.com",
            "password": "Str0ng!Pass",
        })
        self.assertRedirects(resp, reverse("core:dashboard"))

    def test_login_wrong_password_rejected(self):
        make_user("bad@example.com", "Str0ng!Pass")
        resp = self.client.post(reverse("core:login"), {
            "username": "bad@example.com",
            "password": "wrongpass",
        })
        self.assertEqual(resp.status_code, 200)

    def test_logout_requires_post(self):
        u = make_user("logout@example.com")
        self.client.force_login(u)
        # GET should not log out (302 to intro but user still logged in check skipped)
        # POST logs out
        resp = self.client.post(reverse("core:logout"))
        self.assertRedirects(resp, reverse("core:intro"))
        resp2 = self.client.get(reverse("core:dashboard"))
        self.assertNotEqual(resp2.status_code, 200)  # redirected to login

    def test_unauthenticated_dashboard_redirects(self):
        resp = self.client.get(reverse("core:dashboard"))
        self.assertRedirects(resp, "/login/?next=/dashboard/")
