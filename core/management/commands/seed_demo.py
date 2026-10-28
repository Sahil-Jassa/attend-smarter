"""Management command: seed_demo.

Creates a demo user with 4 sample subjects and attendance snapshots.

Usage:
    python manage.py seed_demo
    python manage.py seed_demo --email demo@example.com --password demo1234
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from core.models import Subject, AttendanceSnapshot


DEMO_SUBJECTS = [
    {
        "name": "Data Structures",
        "total_planned": 60,
        "internal_marks": 48,
        "snapshots": [
            (10, 9), (20, 18), (30, 25), (40, 30),
        ],
    },
    {
        "name": "Operating Systems",
        "total_planned": 45,
        "internal_marks": 35,
        "snapshots": [
            (10, 6), (20, 11), (30, 16), (38, 20),
        ],
    },
    {
        "name": "Computer Networks",
        "total_planned": 50,
        "internal_marks": 52,
        "snapshots": [
            (10, 10), (20, 20), (30, 30), (40, 40),
        ],
    },
    {
        "name": "Database Systems",
        "total_planned": 55,
        "internal_marks": 9,
        "snapshots": [
            (10, 3), (20, 5), (30, 7), (40, 9),
        ],
    },
]


class Command(BaseCommand):
    help = "Seed a demo user with 4 sample subjects and attendance snapshots."

    def add_arguments(self, parser):
        parser.add_argument("--email", default="demo@plannerapp.com")
        parser.add_argument("--password", default="Demo@1234")

    def handle(self, *args, **options):
        email = options["email"].lower()
        password = options["password"]

        user, created = User.objects.get_or_create(
            username=email,
            defaults={"email": email},
        )
        if created:
            user.set_password(password)
            user.save()
            self.stdout.write(f"  Created user: {email}")
        else:
            self.stdout.write(f"  User already exists: {email}")

        for sd in DEMO_SUBJECTS:
            subj, _ = Subject.objects.update_or_create(
                user=user,
                name=sd["name"],
                defaults={
                    "total_planned": sd["total_planned"],
                    "internal_marks": sd["internal_marks"],
                },
            )
            # Remove old snapshots for idempotency
            subj.snapshots.all().delete()

            for held, attended in sd["snapshots"]:
                snap = AttendanceSnapshot(subject=subj, held=held, attended=attended)
                snap.full_clean()
                snap.save()

            self.stdout.write(f"  Seeded: {sd['name']}")

        self.stdout.write(self.style.SUCCESS(
            f"\nDemo user ready.\n  Email:    {email}\n  Password: {password}\n  URL:      http://127.0.0.1:8000/"
        ))
