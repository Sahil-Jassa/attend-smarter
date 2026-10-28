"""Views for the Attendance & Grade Planner.

All business logic is delegated to core.services.*
Views handle HTTP, auth, ownership, and context assembly only.
"""

import json
from datetime import date, datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from dotenv import load_dotenv

from .forms import (
    CalendarSetupForm,
    EmailLoginForm,
    EmailSignupForm,
    InternalMarksForm,
    ProfileSettingsForm,
    SnapshotForm,
    SubjectForm,
)
from .models import AttendanceSnapshot, Calendar, CalendarDay, Subject, TimetableSlot
from .services.attendance import (
    compute_all,
    must_attend,
    precompute_slider,
    remaining,
    required_total,
    safe_skips,
)
from .services.skip_planner import safe_skip_days
from .services.calendar_count import (
    build_working_calendar,
    get_ist_today,
    get_national_holidays,
)
from .services.extract import (
    extract_holidays_from_image,
    extract_timetable_from_image,
    validate_upload_file,
)
from .services.marks import grade_table
from .services.risk import compute_risk



# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_threshold(request):
    """Return the active threshold for the current user."""
    profile = request.user.profile
    return profile.medical_threshold if profile.medical_mode else profile.normal_threshold


def _subject_or_404(request, pk):
    """Return the Subject iff it belongs to request.user, else 404."""
    subject = get_object_or_404(Subject, pk=pk)
    if subject.user_id != request.user.pk:
        raise Http404("Subject not found.")
    return subject


def _build_card_data(subject, threshold_75, threshold_65):
    """Pre-compute all display values for a subject card.

    Returns a dict serialisable as JSON (all Python primitives).
    Both threshold outcomes are pre-computed so JS only reads values.
    """
    snap = subject.snapshots.order_by("-recorded_at").first()
    counts = subject.compute_attendance_counts()
    if counts:
        T = counts["total"]
        H = counts["held"]
        if T > 0 and subject.total_planned != T:
            subject.total_planned = T
            Subject.objects.filter(pk=subject.pk).update(total_planned=T)
    else:
        T = subject.total_planned
        H = snap.held if snap else 0

    A = snap.attended if snap else 0
    if A > H:
        A = H

    data_75 = compute_all(H, A, T, threshold_75)
    data_65 = compute_all(H, A, T, threshold_65)
    slider_75 = precompute_slider(H, A, T, threshold_75)
    slider_65 = precompute_slider(H, A, T, threshold_65)

    return {
        "pk": subject.pk,
        "name": subject.name,
        "total_planned": T,
        "held": H,
        "attended": A,
        "data_75": data_75,
        "data_65": data_65,
        "slider_75": slider_75,
        "slider_65": slider_65,
    }


def _get_user_skip_plan(user, active_thr: int):
    """Compute safe-skip ranking and greedy plan for the user's active calendar and subjects."""
    calendar = user.calendars.order_by("-created_at").first()
    subjects = Subject.objects.filter(user=user).prefetch_related("snapshots", "slots").order_by("created_at")
    if not calendar or not subjects.exists():
        return None

    holidays = [d.date for d in calendar.days.filter(kind="holiday")]
    working_overrides = [
        d.date for d in calendar.days.filter(kind="working")
        if d.date.weekday() in (5, 6)
    ]
    custom_day_orders = {
        d.date: d.day_order
        for d in calendar.days.filter(kind="working", day_order__isnull=False)
    }

    today = get_ist_today()
    subjects_payload = []
    for s in subjects:
        snap = s.snapshots.order_by("-recorded_at").first()
        counts = s.compute_attendance_counts(today=today)
        if counts:
            T = counts["total"]
            H = counts["held"]
        else:
            T = s.total_planned
            H = snap.held if snap else 0
        A = snap.attended if snap else 0
        if A > H:
            A = H
        r = remaining(T, H)
        req = required_total(T, active_thr)
        must = must_attend(A, req)
        budget = safe_skips(r, must)
        slots = list(s.slots.values("weekday", "day_order", "periods"))
        subjects_payload.append({
            "id": s.pk,
            "name": s.name,
            "slots": slots,
            "budget": budget,
            "held": H,
            "attended": A,
            "total_planned": T,
        })

    plan_result = safe_skip_days(
        today=today,
        end=calendar.last_working_day,
        start=calendar.start_date,
        holidays=holidays,
        working_overrides=working_overrides,
        weekends_off=calendar.weekends_off,
        subjects=subjects_payload,
        day_order_mode=(calendar.mode == "day_order"),
        custom_day_orders=custom_day_orders,
        threshold=active_thr,
    )

    subject_budget_rows = []
    for s in subjects_payload:
        s_id = s["id"]
        init_b = plan_result["initial_budgets"].get(s_id, 0)
        left_b = plan_result["budget_left"].get(s_id, 0)
        used_b = init_b - left_b
        subject_budget_rows.append({
            "id": s_id,
            "name": s["name"],
            "initial_budget": init_b,
            "used_budget": used_b,
            "left_budget": left_b,
        })
    plan_result["subject_budget_rows"] = subject_budget_rows
    plan_result["top_feasible"] = plan_result["feasible_days"][:5]

    return plan_result


# ── Landing / Intro ───────────────────────────────────────────────────────────

def intro_view(request):
    """Show the intro/landing page. Authenticated users go straight to dashboard."""
    if request.user.is_authenticated:
        return redirect("core:dashboard")

    login_form = EmailLoginForm()
    signup_form = EmailSignupForm()
    return render(request, "intro.html", {
        "login_form": login_form,
        "signup_form": signup_form,
    })


# ── Auth ──────────────────────────────────────────────────────────────────────

def signup_view(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")

    if request.method == "POST":
        form = EmailSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Welcome! Your account has been created.")
            return redirect("core:dashboard")
        # Fall through to render with errors
        login_form = EmailLoginForm()
        return render(request, "intro.html", {
            "login_form": login_form,
            "signup_form": form,
            "active_tab": "signup",
        })

    login_form = EmailLoginForm()
    signup_form = EmailSignupForm()
    return render(request, "intro.html", {
        "login_form": login_form,
        "signup_form": signup_form,
        "active_tab": "signup",
    })


def login_view(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")

    if request.method == "POST":
        form = EmailLoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            next_url = request.POST.get("next") or request.GET.get("next") or "core:dashboard"
            return redirect(next_url)
        signup_form = EmailSignupForm()
        return render(request, "intro.html", {
            "login_form": form,
            "signup_form": signup_form,
            "active_tab": "login",
        })

    login_form = EmailLoginForm()
    signup_form = EmailSignupForm()
    return render(request, "intro.html", {
        "login_form": login_form,
        "signup_form": signup_form,
        "active_tab": "login",
    })


@require_POST
def logout_view(request):
    """Logout via POST form only (Django 5 best practice)."""
    logout(request)
    return redirect("core:intro")


# ── Medical mode toggle ───────────────────────────────────────────────────────

@login_required
def toggle_medical_view(request):
    """Toggle medical mode via POST. Returns JSON for fetch, or redirects for no-JS."""
    profile = request.user.profile
    if request.method == "POST":
        profile.medical_mode = not profile.medical_mode
        profile.save()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"medical_mode": profile.medical_mode})
        return redirect("core:dashboard")
    # No-JS fallback GET: show a plain form on the dashboard
    return redirect("core:dashboard")


# ── Dashboard ─────────────────────────────────────────────────────────────────

@login_required
def dashboard_view(request):
    profile = request.user.profile
    subjects = Subject.objects.filter(user=request.user).prefetch_related("snapshots").order_by("created_at")
    calendar = request.user.calendars.order_by("-created_at").first()

    thr_normal = profile.normal_threshold
    thr_medical = profile.medical_threshold
    active_thr = thr_medical if profile.medical_mode else thr_normal

    cards = []
    status_counts = {"safe": 0, "warning": 0, "detention_zone": 0, "no_classes": 0}

    for subj in subjects:
        card = _build_card_data(subj, thr_normal, thr_medical)
        active_data = card["data_65"] if profile.medical_mode else card["data_75"]
        status = active_data["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
        cards.append(card)

    skip_plan = _get_user_skip_plan(request.user, active_thr)

    return render(request, "dashboard.html", {
        "profile": profile,
        "calendar": calendar,
        "cards": cards,
        "cards_json": json.dumps(cards),
        "active_thr": active_thr,
        "status_counts": status_counts,
        "medical_mode": profile.medical_mode,
        "skip_plan": skip_plan,
    })


# ── Calendar Setup, Preview, and Save ─────────────────────────────────────────

@login_required
def calendar_setup_view(request):
    env_file = settings.BASE_DIR / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=True)

    existing_cal = request.user.calendars.order_by("-created_at").first()

    if request.method == "POST":
        form = CalendarSetupForm(request.POST, request.FILES)
        if form.is_valid():
            start_date = form.cleaned_data["start_date"]
            last_working_day = form.cleaned_data["last_working_day"]
            weekends_off = form.cleaned_data["weekends_off"]
            mode = form.cleaned_data["mode"]

            subjects = []
            holidays = []

            # 1. Process timetable upload
            tt_file = request.FILES.get("timetable_file")
            if tt_file:
                file_bytes = tt_file.read()
                valid, err = validate_upload_file(file_bytes, tt_file.name)
                if not valid:
                    messages.error(request, f"Timetable file error: {err}")
                else:
                    tt_res = extract_timetable_from_image(file_bytes, filename=tt_file.name, mode=mode)
                    if tt_res["success"]:
                        subjects = tt_res["data"]["valid_subjects"]
                        messages.success(request, f"Extracted {len(subjects)} subjects from your timetable!")
                    else:
                        messages.warning(request, tt_res["error"])

            # 2. Process holiday upload
            hol_file = request.FILES.get("holiday_file")
            if hol_file:
                file_bytes = hol_file.read()
                valid, err = validate_upload_file(file_bytes, hol_file.name)
                if not valid:
                    messages.error(request, f"Holiday calendar file error: {err}")
                else:
                    hol_res = extract_holidays_from_image(
                        file_bytes, filename=hol_file.name,
                        start_date=start_date, last_working_day=last_working_day
                    )
                    if hol_res["success"]:
                        holidays = hol_res["data"]["valid_holidays"]
                        messages.success(request, f"Extracted {len(holidays)} holidays from calendar document!")
                    else:
                        messages.warning(request, hol_res["error"])

            # 3. Prefill fixed national holidays (26 Jan, 15 Aug, 2 Oct) falling in range
            nat_holidays = get_national_holidays(start_date, last_working_day)
            existing_dates = set()
            for h in holidays:
                if "date" in h:
                    d_val = h["date"]
                    existing_dates.add(d_val.isoformat() if hasattr(d_val, "isoformat") else str(d_val))
                elif "start" in h:
                    d_val = h["start"]
                    existing_dates.add(d_val.isoformat() if hasattr(d_val, "isoformat") else str(d_val))

            for nh in nat_holidays:
                d_str = nh["date"].isoformat()
                if d_str not in existing_dates:
                    holidays.append({"date": d_str, "label": nh["label"]})
                    existing_dates.add(d_str)

            # Format holidays for JSON serialisation
            serializable_holidays = []
            for h in holidays:
                item = {"label": h.get("label", "Holiday")}
                if "date" in h:
                    item["date"] = h["date"].isoformat() if hasattr(h["date"], "isoformat") else str(h["date"])
                if "start" in h:
                    item["start"] = h["start"].isoformat() if hasattr(h["start"], "isoformat") else str(h["start"])
                if "end" in h:
                    item["end"] = h["end"].isoformat() if hasattr(h["end"], "isoformat") else str(h["end"])
                serializable_holidays.append(item)

            # If user already has subjects and didn't upload a timetable, prefill existing subjects
            if not subjects and existing_cal:
                user_subjects = Subject.objects.filter(user=request.user).prefetch_related("slots")
                for s in user_subjects:
                    slots = []
                    for slot in s.slots.all():
                        slots.append({
                            "weekday_or_day_order": slot.day_order if mode == "day_order" and slot.day_order is not None else slot.weekday,
                            "periods": slot.periods,
                        })
                    subjects.append({"name": s.name, "slots": slots})

            # Save draft in session
            request.session["calendar_setup_draft"] = {
                "start_date": start_date.isoformat(),
                "last_working_day": last_working_day.isoformat(),
                "weekends_off": weekends_off,
                "mode": mode,
                "subjects": subjects,
                "holidays": serializable_holidays,
            }
            return redirect("core:calendar_preview")
    else:
        initial = {}
        if existing_cal:
            initial = {
                "start_date": existing_cal.start_date,
                "last_working_day": existing_cal.last_working_day,
                "weekends_off": existing_cal.weekends_off,
                "mode": existing_cal.mode,
            }
        form = CalendarSetupForm(initial=initial)

    return render(request, "calendar_setup.html", {"form": form, "existing_cal": existing_cal})


@login_required
def calendar_preview_view(request):
    draft = request.session.get("calendar_setup_draft")
    if not draft:
        messages.info(request, "Please set up your semester dates first.")
        return redirect("core:calendar_setup")

    start_date = datetime.strptime(draft["start_date"], "%Y-%m-%d").date()
    last_working_day = datetime.strptime(draft["last_working_day"], "%Y-%m-%d").date()
    weekends_off = draft.get("weekends_off", True)
    mode = draft.get("mode", "weekday")

    # Parse holidays into dates or date ranges
    parsed_holidays = []
    for h in draft.get("holidays", []):
        if "start" in h and "end" in h:
            d1 = datetime.strptime(h["start"], "%Y-%m-%d").date() if isinstance(h["start"], str) else h["start"]
            d2 = datetime.strptime(h["end"], "%Y-%m-%d").date() if isinstance(h["end"], str) else h["end"]
            parsed_holidays.append((d1, d2))
        elif "date" in h:
            d = datetime.strptime(h["date"], "%Y-%m-%d").date() if isinstance(h["date"], str) else h["date"]
            parsed_holidays.append(d)

    cal_days = build_working_calendar(
        start=start_date,
        end=last_working_day,
        holidays=parsed_holidays,
        weekends_off=weekends_off,
        day_order_mode=(mode == "day_order"),
    )

    total_working_days = sum(1 for d in cal_days if d["is_working"])
    total_holidays_skipped = sum(1 for d in cal_days if d["is_holiday"])
    total_calendar_days = len(cal_days)

    # Group month-by-month
    month_map = {}
    for d in cal_days:
        m_key = d["date"].strftime("%B %Y")
        if m_key not in month_map:
            month_map[m_key] = {"month": m_key, "working": 0, "holidays": 0, "weekends": 0}
        if d["is_working"]:
            month_map[m_key]["working"] += 1
        elif d["is_holiday"]:
            month_map[m_key]["holidays"] += 1
        elif d["is_weekend"]:
            month_map[m_key]["weekends"] += 1

    months_list = list(month_map.values())

    return render(request, "calendar_preview.html", {
        "draft": draft,
        "start_date": start_date,
        "last_working_day": last_working_day,
        "weekends_off": weekends_off,
        "mode": mode,
        "subjects": draft.get("subjects", []),
        "holidays": draft.get("holidays", []),
        "total_calendar_days": total_calendar_days,
        "total_working_days": total_working_days,
        "total_holidays_skipped": total_holidays_skipped,
        "months_list": months_list,
        "weekday_choices": [
            (0, "Monday"), (1, "Tuesday"), (2, "Wednesday"),
            (3, "Thursday"), (4, "Friday"), (5, "Saturday"), (6, "Sunday"),
        ],
    })


@login_required
@require_POST
def calendar_save_view(request):
    draft = request.session.get("calendar_setup_draft")
    if not draft:
        messages.error(request, "Setup session expired. Please configure your calendar again.")
        return redirect("core:calendar_setup")

    start_date = datetime.strptime(draft["start_date"], "%Y-%m-%d").date()
    last_working_day = datetime.strptime(draft["last_working_day"], "%Y-%m-%d").date()
    weekends_off = draft.get("weekends_off", True)
    mode = draft.get("mode", "weekday")

    # Read updated JSON payload from preview form if provided
    subjects_json = request.POST.get("confirmed_subjects")
    holidays_json = request.POST.get("confirmed_holidays")

    try:
        subjects = json.loads(subjects_json) if subjects_json else draft.get("subjects", [])
    except json.JSONDecodeError:
        subjects = draft.get("subjects", [])

    try:
        holidays = json.loads(holidays_json) if holidays_json else draft.get("holidays", [])
    except json.JSONDecodeError:
        holidays = draft.get("holidays", [])

    # 1. Update or create Calendar
    calendar, _ = Calendar.objects.update_or_create(
        user=request.user,
        defaults={
            "start_date": start_date,
            "last_working_day": last_working_day,
            "weekends_off": weekends_off,
            "mode": mode,
        },
    )

    # 2. Reset and create CalendarDay records
    calendar.days.all().delete()
    for h in holidays:
        label = h.get("label", "Holiday")
        if "start" in h and "end" in h:
            d_start = datetime.strptime(h["start"], "%Y-%m-%d").date() if isinstance(h["start"], str) else h["start"]
            d_end = datetime.strptime(h["end"], "%Y-%m-%d").date() if isinstance(h["end"], str) else h["end"]
            curr = d_start
            while curr <= d_end:
                CalendarDay.objects.update_or_create(
                    calendar=calendar,
                    date=curr,
                    defaults={"kind": CalendarDay.KIND_HOLIDAY, "label": label},
                )
                curr += timedelta(days=1)
        elif "date" in h:
            d = datetime.strptime(h["date"], "%Y-%m-%d").date() if isinstance(h["date"], str) else h["date"]
            CalendarDay.objects.update_or_create(
                calendar=calendar,
                date=d,
                defaults={"kind": CalendarDay.KIND_HOLIDAY, "label": label},
            )

    # 3. Create or update Subjects & TimetableSlot records
    for s_data in subjects:
        s_name = s_data.get("name", "").strip()
        if not s_name:
            continue
        subj, _ = Subject.objects.get_or_create(
            user=request.user,
            name=s_name,
            defaults={"total_planned": 1},
        )
        subj.slots.all().delete()

        for slot in s_data.get("slots", []):
            try:
                p = int(slot.get("periods", 1))
            except (ValueError, TypeError):
                p = 1
            raw_k = slot.get("weekday_or_day_order")
            if raw_k is None:
                raw_k = slot.get("weekday") if slot.get("weekday") is not None else slot.get("day_order")
            if raw_k is None:
                continue
            try:
                k = int(raw_k)
            except (ValueError, TypeError):
                continue

            if mode == "day_order":
                TimetableSlot.objects.create(subject=subj, day_order=k, periods=p)
            else:
                TimetableSlot.objects.create(subject=subj, weekday=k, periods=p)

        # Compute initial total_planned for this subject
        counts = subj.compute_attendance_counts()
        if counts and counts["total"] > 0:
            subj.total_planned = counts["total"]
            subj.save()

    request.session.pop("calendar_setup_draft", None)
    messages.success(request, "Semester calendar and timetable saved successfully!")
    return redirect("core:dashboard")


# ── Subject views ─────────────────────────────────────────────────────────────

@login_required
def subject_add_view(request):
    if request.method == "POST":
        form = SubjectForm(request.POST)
        if form.is_valid():
            subject = form.save(commit=False)
            subject.user = request.user
            subject.save()
            messages.success(request, f"Subject '{subject.name}' added.")
            return redirect("core:dashboard")
    else:
        form = SubjectForm()
    return render(request, "subject_form.html", {"form": form, "action": "Add"})


@login_required
def subject_edit_view(request, pk):
    subject = _subject_or_404(request, pk)
    if request.method == "POST":
        form = SubjectForm(request.POST, instance=subject)
        if form.is_valid():
            form.save()
            messages.success(request, f"'{subject.name}' updated.")
            return redirect("core:subject_detail", pk=pk)
    else:
        form = SubjectForm(instance=subject)
    return render(request, "subject_form.html", {"form": form, "action": "Edit", "subject": subject})


@login_required
@require_POST
def subject_delete_view(request, pk):
    subject = _subject_or_404(request, pk)
    name = subject.name
    subject.delete()
    messages.success(request, f"'{name}' deleted.")
    return redirect("core:dashboard")


@login_required
def subject_detail_view(request, pk):
    subject = _subject_or_404(request, pk)
    profile = request.user.profile
    active_thr = profile.medical_threshold if profile.medical_mode else profile.normal_threshold

    snap = subject.snapshots.order_by("-recorded_at").first()
    counts = subject.compute_attendance_counts(today=get_ist_today())
    if counts:
        T = counts["total"]
        H = counts["held"]
        if T > 0 and subject.total_planned != T:
            subject.total_planned = T
            Subject.objects.filter(pk=subject.pk).update(total_planned=T)
    else:
        T = subject.total_planned
        H = snap.held if snap else 0

    A = snap.attended if snap else 0
    if A > H:
        A = H

    att = compute_all(H, A, T, active_thr)
    risk = compute_risk(H, A, T, active_thr)
    g_table = grade_table(subject.internal_marks) if subject.internal_marks is not None else None
    slider_data = precompute_slider(H, A, T, active_thr)

    # Snapshots for trend chart (chronological)
    snapshots = list(
        subject.snapshots.order_by("recorded_at").values("held", "attended", "recorded_at")
    )
    trend_labels = [s["recorded_at"].strftime("%b %d") for s in snapshots]
    trend_pct = [
        round(s["attended"] / s["held"] * 100, 1) if s["held"] > 0 else 0
        for s in snapshots
    ]

    snapshot_form = SnapshotForm(subject=subject)
    internal_form = InternalMarksForm(instance=subject)

    skip_plan = _get_user_skip_plan(request.user, active_thr)
    subject_plan_days = []
    subject_initial_budget = 0
    subject_budget_left = 0
    subject_skips_used = 0
    if skip_plan:
        subject_initial_budget = skip_plan["initial_budgets"].get(subject.pk, 0)
        subject_budget_left = skip_plan["budget_left"].get(subject.pk, 0)
        subject_skips_used = subject_initial_budget - subject_budget_left
        subject_plan_days = [
            {
                "date": d["date"],
                "date_str": d["date_str"],
                "weekday_name": d["weekday_name"],
                "label": d["label"],
                "periods": d["costs"].get(subject.pk, 0),
            }
            for d in skip_plan["plan"]
            if d["costs"].get(subject.pk, 0) > 0
        ]

    return render(request, "subject_detail.html", {
        "subject": subject,
        "profile": profile,
        "snap": snap,
        "counts": counts,
        "H": H, "A": A, "T": T,
        "att": att,
        "risk": risk,
        "grade_table": g_table,
        "slider_data_json": json.dumps(slider_data),
        "trend_labels_json": json.dumps(trend_labels),
        "trend_pct_json": json.dumps(trend_pct),
        "active_thr": active_thr,
        "snapshot_form": snapshot_form,
        "internal_form": internal_form,
        "skip_plan": skip_plan,
        "subject_plan_days": subject_plan_days,
        "subject_initial_budget": subject_initial_budget,
        "subject_budget_left": subject_budget_left,
        "subject_skips_used": subject_skips_used,
    })



# ── Snapshot (attendance update) ──────────────────────────────────────────────

@login_required
@require_POST
def snapshot_add_view(request, pk):
    subject = _subject_or_404(request, pk)
    form = SnapshotForm(request.POST, subject=subject)
    if form.is_valid():
        snap = form.save(commit=False)
        snap.subject = subject
        snap.save()
        messages.success(request, "Attendance updated.")
    else:
        for field_errors in form.errors.values():
            for err in field_errors:
                messages.error(request, err)
    return redirect("core:subject_detail", pk=pk)


# ── Internal marks ────────────────────────────────────────────────────────────

@login_required
@require_POST
def internal_marks_view(request, pk):
    subject = _subject_or_404(request, pk)
    form = InternalMarksForm(request.POST, instance=subject)
    if form.is_valid():
        form.save()
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"ok": True, "internal_marks": subject.internal_marks})
        messages.success(request, "Internal marks saved.")
    else:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "errors": form.errors}, status=400)
        messages.error(request, "Invalid internal marks value.")
    return redirect("core:subject_detail", pk=pk)


# ── Settings ──────────────────────────────────────────────────────────────────

@login_required
def settings_view(request):
    profile = request.user.profile
    if request.method == "POST":
        form = ProfileSettingsForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Settings saved.")
            return redirect("core:dashboard")
    else:
        form = ProfileSettingsForm(instance=profile)
    return render(request, "settings.html", {"form": form})
