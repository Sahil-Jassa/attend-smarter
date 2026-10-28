from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from .models import Profile, Subject, AttendanceSnapshot


# ── Auth forms ────────────────────────────────────────────────────────────────

class EmailSignupForm(UserCreationForm):
    """Signup form using email as the username field."""

    email = forms.EmailField(
        required=True,
        max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email", "id": "id_signup_email"}),
    )

    class Meta:
        model = User
        fields = ("email", "password1", "password2")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(username=email).exists():
            raise forms.ValidationError("An account with that email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data["email"].lower()
        user.email = self.cleaned_data["email"].lower()
        if commit:
            user.save()
        return user


class EmailLoginForm(AuthenticationForm):
    """Login form that uses email as the username field."""

    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "id": "id_login_email"}),
    )

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


# ── Subject / Snapshot forms ──────────────────────────────────────────────────

class SubjectForm(forms.ModelForm):
    """Create or edit a Subject."""

    class Meta:
        model = Subject
        fields = ("name", "total_planned", "held_adjustment", "internal_marks")
        widgets = {
            "name": forms.TextInput(attrs={"autocomplete": "off"}),
            "total_planned": forms.NumberInput(attrs={"min": 1}),
            "held_adjustment": forms.NumberInput(attrs={"placeholder": "0"}),
            "internal_marks": forms.NumberInput(attrs={"min": 0, "max": 60}),
        }

    def clean_total_planned(self):
        val = self.cleaned_data.get("total_planned")
        if val is not None and val <= 0:
            raise ValidationError("Total planned must be > 0.")
        return val

    def clean_internal_marks(self):
        val = self.cleaned_data.get("internal_marks")
        if val is not None and not (0 <= val <= 60):
            raise ValidationError("Internal marks must be between 0 and 60.")
        return val

    def clean(self):
        cleaned = super().clean()
        if self.instance and self.instance.pk:
            tp = cleaned.get("total_planned")
            latest = self.instance.snapshots.order_by("-recorded_at").first()
            if tp is not None and latest and tp < latest.held:
                self.add_error(
                    "total_planned",
                    f"Total planned cannot be less than current held ({latest.held}).",
                )
        return cleaned


class SnapshotForm(forms.ModelForm):
    """Add an attendance snapshot for a subject with auto-calendar or manual mode."""

    entry_mode = forms.ChoiceField(
        choices=[
            ("attended", "Attended Classes"),
            ("absences", "Absences / Missed Classes"),
            ("manual", "Manual (Held + Attended)"),
        ],
        required=False,
        initial="attended",
    )
    absences = forms.IntegerField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={"min": 0, "placeholder": "e.g. 2", "id": "id_absences"}),
    )
    held_adjustment = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={"placeholder": "0", "id": "id_held_adjustment"}),
        help_text="Adjust held for cancelled (-1) or extra classes (+1)",
    )

    class Meta:
        model = AttendanceSnapshot
        fields = ("held", "attended")
        widgets = {
            "held": forms.NumberInput(attrs={"min": 0, "id": "id_held"}),
            "attended": forms.NumberInput(attrs={"min": 0, "id": "id_attended"}),
        }

    def __init__(self, *args, subject=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._subject = subject
        self._computed = None
        if subject:
            self._computed = subject.compute_attendance_counts()
            if self._computed:
                # Pre-populate held from calendar counting
                self.fields["held"].initial = self._computed["held"]
                self.fields["held"].required = False
                self.fields["attended"].required = False
                self.fields["held_adjustment"].initial = subject.held_adjustment

    def clean(self):
        cleaned = super().clean()
        entry_mode = cleaned.get("entry_mode") or "attended"
        held = cleaned.get("held")
        attended = cleaned.get("attended")
        absences = cleaned.get("absences")
        held_adj = cleaned.get("held_adjustment")

        # Update subject held adjustment if provided
        if self._subject and held_adj is not None and held_adj != self._subject.held_adjustment:
            self._subject.held_adjustment = held_adj
            self._subject.save(update_fields=["held_adjustment"])
            # Recompute with updated adjustment
            self._computed = self._subject.compute_attendance_counts()

        # If held is missing but auto-computed is available, use computed held
        if held is None and self._computed:
            held = self._computed["held"]
            cleaned["held"] = held

        if entry_mode == "absences":
            if absences is None:
                self.add_error("absences", "Please enter the number of absences.")
            else:
                if held is None:
                    held = self._computed["held"] if self._computed else 0
                    cleaned["held"] = held
                attended = max(0, held - absences)
                cleaned["attended"] = attended
        elif entry_mode == "attended":
            if attended is None:
                # If only held was known, attended cannot be blank
                self.add_error("attended", "Please enter attended classes.")

        if held is not None and attended is not None:
            if attended > held:
                self.add_error("attended", "Attended cannot be more than held.")
            if self._subject and held > self._subject.total_planned:
                self.add_error(
                    "held",
                    f"Held cannot exceed total planned ({self._subject.total_planned}).",
                )

        return cleaned


class CalendarSetupForm(forms.Form):
    """Academic calendar setup: start date, last working day, mode, and photo uploads."""

    start_date = forms.DateField(
        label="Semester Start Date",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-input"}),
        help_text="First instructional day (inclusive)",
    )
    last_working_day = forms.DateField(
        label="Last Working Day",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-input"}),
        help_text="End of classes / semester (inclusive)",
    )
    weekends_off = forms.BooleanField(
        label="Weekends Off (Skip Saturdays & Sundays)",
        required=False,
        initial=True,
    )
    mode = forms.ChoiceField(
        label="Schedule Mode",
        choices=[
            ("weekday", "Weekday Schedule (Mon - Fri / Sat)"),
            ("day_order", "Day Order Schedule (Day Order 1 to 5)"),
        ],
        initial="weekday",
        widget=forms.Select(attrs={"class": "form-input"}),
    )
    timetable_file = forms.FileField(
        label="Timetable Photo / PDF (Optional)",
        required=False,
        widget=forms.FileInput(attrs={"accept": ".jpg,.jpeg,.png,.pdf", "class": "form-input"}),
        help_text="Upload your weekly timetable. Max 5 MB (JPG, PNG, PDF).",
    )
    holiday_file = forms.FileField(
        label="Holiday Calendar Photo / PDF (Optional)",
        required=False,
        widget=forms.FileInput(attrs={"accept": ".jpg,.jpeg,.png,.pdf", "class": "form-input"}),
        help_text="Upload your college holiday list. Max 5 MB (JPG, PNG, PDF).",
    )

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("last_working_day")
        if start and end and start > end:
            self.add_error("last_working_day", "Last working day must be on or after start date.")
        return cleaned



class ProfileSettingsForm(forms.ModelForm):
    """Edit attendance thresholds."""

    class Meta:
        model = Profile
        fields = ("normal_threshold", "medical_threshold", "medical_mode")
        widgets = {
            "normal_threshold": forms.NumberInput(attrs={"min": 50, "max": 90}),
            "medical_threshold": forms.NumberInput(attrs={"min": 50, "max": 90}),
        }

    def clean(self):
        cleaned = super().clean()
        nt = cleaned.get("normal_threshold")
        mt = cleaned.get("medical_threshold")
        if nt is not None and mt is not None and mt > nt:
            self.add_error("medical_threshold", "Medical threshold must be <= normal threshold.")
        return cleaned


class InternalMarksForm(forms.ModelForm):
    """Update internal marks for a subject."""

    class Meta:
        model = Subject
        fields = ("internal_marks",)
        widgets = {
            "internal_marks": forms.NumberInput(attrs={"min": 0, "max": 60}),
        }
