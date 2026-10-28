from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator


class Profile(models.Model):
    """One-to-one extension of the built-in User.

    Stores attendance thresholds and medical mode flag.
    Created automatically via a signal on User creation.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    medical_mode = models.BooleanField(default=False)
    normal_threshold = models.PositiveSmallIntegerField(
        default=75,
        validators=[MinValueValidator(50), MaxValueValidator(90)],
        help_text="Normal attendance threshold (50-90)",
    )
    medical_threshold = models.PositiveSmallIntegerField(
        default=65,
        validators=[MinValueValidator(50), MaxValueValidator(90)],
        help_text="Medical attendance threshold (50-90, must be <= normal_threshold)",
    )

    def clean(self):
        super().clean()
        if self.medical_threshold > self.normal_threshold:
            raise ValidationError(
                {'medical_threshold': 'Medical threshold must be <= normal threshold.'}
            )

    def __str__(self):
        return f"Profile of {self.user.email or self.user.username}"


class Subject(models.Model):
    """A subject owned by a user."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subjects')
    name = models.CharField(max_length=100)
    total_planned = models.PositiveIntegerField(help_text="T: total number of classes planned")
    internal_marks = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(60)],
        help_text="Internal marks out of 60",
    )
    held_adjustment = models.IntegerField(
        default=0,
        help_text="Adjustment for cancelled or extra classes (+/-)",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        if self.total_planned is not None and self.total_planned <= 0:
            raise ValidationError({'total_planned': 'Total planned must be > 0.'})
        if self.internal_marks is not None and not (0 <= self.internal_marks <= 60):
            raise ValidationError({'internal_marks': 'Internal marks must be between 0 and 60.'})
        # Reject total_planned below the latest snapshot held value.
        if self.pk:
            latest = self.snapshots.order_by('-recorded_at').first()
            if latest and self.total_planned < latest.held:
                raise ValidationError(
                    {'total_planned': f"Total planned cannot be less than current held ({latest.held})."}
                )

    def compute_attendance_counts(self, today=None):
        """Compute total and held classes using the user's active calendar and this subject's timetable slots."""
        calendar = self.user.calendars.order_by('-created_at').first()
        if not calendar:
            return None
        from core.services.calendar_count import count_classes

        holidays = [d.date for d in calendar.days.filter(kind='holiday')]
        working_overrides = [
            d.date for d in calendar.days.filter(kind='working')
            if d.date.weekday() in (5, 6)
        ]
        custom_day_orders = {
            d.date: d.day_order
            for d in calendar.days.filter(kind='working', day_order__isnull=False)
        }
        slots = list(self.slots.values('weekday', 'day_order', 'periods'))

        return count_classes(
            start=calendar.start_date,
            end=calendar.last_working_day,
            today=today,
            holidays=holidays,
            working_overrides=working_overrides,
            weekends_off=calendar.weekends_off,
            slots=slots,
            day_order_mode=(calendar.mode == 'day_order'),
            custom_day_orders=custom_day_orders,
            held_adjustment=self.held_adjustment,
        )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class AttendanceSnapshot(models.Model):
    """Immutable snapshot of attendance (H=held, A=attended) at a point in time."""

    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='snapshots')
    held = models.PositiveIntegerField(help_text="H: classes held so far")
    attended = models.PositiveIntegerField(help_text="A: classes attended so far")
    recorded_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        super().clean()
        if self.attended is not None and self.held is not None:
            if not (0 <= self.attended <= self.held):
                raise ValidationError({'attended': 'Attended cannot exceed held.'})
        if self.subject_id and self.held is not None and self.held > self.subject.total_planned:
            raise ValidationError({'held': 'Held cannot exceed total planned for the subject.'})

    def save(self, *args, **kwargs):
        # Enforce validation on every save, not just via forms.
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.subject.name}: {self.attended}/{self.held} on {self.recorded_at:%Y-%m-%d}"


class Calendar(models.Model):
    """Academic semester calendar configuration for a user."""

    MODE_WEEKDAY = 'weekday'
    MODE_DAY_ORDER = 'day_order'
    MODE_CHOICES = [
        (MODE_WEEKDAY, 'Weekday'),
        (MODE_DAY_ORDER, 'Day Order'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='calendars')
    start_date = models.DateField(help_text="First day of semester (inclusive)")
    last_working_day = models.DateField(help_text="Last working day (inclusive)")
    weekends_off = models.BooleanField(default=True, help_text="Skip Saturdays and Sundays")
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default=MODE_WEEKDAY)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if self.start_date and self.last_working_day and self.start_date > self.last_working_day:
            raise ValidationError({'last_working_day': 'Last working day must be on or after start date.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Calendar ({self.user.username}): {self.start_date} to {self.last_working_day} ({self.mode})"


class CalendarDay(models.Model):
    """Specific calendar date override, holiday, or day-order mapping."""

    KIND_WORKING = 'working'
    KIND_HOLIDAY = 'holiday'
    KIND_CHOICES = [
        (KIND_WORKING, 'Working Day'),
        (KIND_HOLIDAY, 'Holiday'),
    ]

    calendar = models.ForeignKey(Calendar, on_delete=models.CASCADE, related_name='days')
    date = models.DateField()
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_WORKING)
    day_order = models.PositiveSmallIntegerField(null=True, blank=True)
    label = models.CharField(max_length=150, blank=True, default='')

    class Meta:
        unique_together = [('calendar', 'date')]
        ordering = ['date']

    def __str__(self):
        return f"{self.date}: {self.kind} ({self.label or 'No label'})"


class TimetableSlot(models.Model):
    """A recurring timetable slot for a subject."""

    WEEKDAY_CHOICES = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='slots')
    weekday = models.PositiveSmallIntegerField(null=True, blank=True, choices=WEEKDAY_CHOICES)
    day_order = models.PositiveSmallIntegerField(null=True, blank=True)
    periods = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])

    def clean(self):
        super().clean()
        if self.weekday is None and self.day_order is None:
            raise ValidationError("Either weekday or day_order must be set.")
        if self.periods is not None and self.periods < 1:
            raise ValidationError({'periods': 'Periods must be at least 1.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        day_str = f"Day Order {self.day_order}" if self.day_order is not None else dict(self.WEEKDAY_CHOICES).get(self.weekday, str(self.weekday))
        return f"{self.subject.name} - {day_str} ({self.periods} periods)"

