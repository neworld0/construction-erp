from django.utils import timezone

from .models import ProjectOperationalTestDateWindow


def get_active_test_date_window(project, *, today=None):
    if project is None:
        return None
    today = today or timezone.localdate()
    window = ProjectOperationalTestDateWindow.objects.filter(project=project, is_enabled=True).first()
    if window and window.expires_on >= today:
        return window
    return None


def allows_future_operational_test_date(project, target_date, *, today=None):
    today = today or timezone.localdate()
    return bool(target_date > today and allows_operational_test_date(project, target_date, today=today))


def allows_operational_test_date(project, target_date, *, today=None):
    """Return whether a project-scoped UAT window authorizes the target date.

    This intentionally covers both past and future dates inside the configured
    project window.  It is used only by FIELD UAT guards; closing guards still
    protect any closed project/month.
    """
    window = get_active_test_date_window(project, today=today)
    return bool(window and window.start_date <= target_date <= window.end_date)
