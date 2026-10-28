from django.urls import path
from . import views

app_name = "core"

urlpatterns = [
    # Landing / intro
    path("", views.intro_view, name="intro"),

    # Auth
    path("signup/", views.signup_view, name="signup"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    # App
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("settings/", views.settings_view, name="settings"),

    # Calendar & Timetable Setup
    path("calendar/setup/", views.calendar_setup_view, name="calendar_setup"),
    path("calendar/preview/", views.calendar_preview_view, name="calendar_preview"),
    path("calendar/save/", views.calendar_save_view, name="calendar_save"),

    # Subject CRUD
    path("subject/add/", views.subject_add_view, name="subject_add"),
    path("subject/<int:pk>/", views.subject_detail_view, name="subject_detail"),
    path("subject/<int:pk>/edit/", views.subject_edit_view, name="subject_edit"),
    path("subject/<int:pk>/delete/", views.subject_delete_view, name="subject_delete"),

    # Snapshot (attendance update)
    path("subject/<int:pk>/snapshot/", views.snapshot_add_view, name="snapshot_add"),

    # Internal marks AJAX
    path("subject/<int:pk>/internal/", views.internal_marks_view, name="internal_marks"),

    # Medical mode toggle
    path("toggle-medical/", views.toggle_medical_view, name="toggle_medical"),
]
