from django.urls import path

from .web_views import (
    hq_labor_rate_edit,
    hq_labor_rate_list,
    hq_labor_rate_new,
    hq_labor_rate_toggle,
    hq_labor_role_edit,
    hq_labor_role_list,
    hq_labor_role_new,
    hq_labor_role_toggle,
)

urlpatterns = [
    path("labor/roles/", hq_labor_role_list),
    path("labor/roles/new/", hq_labor_role_new),
    path("labor/roles/<int:role_id>/edit/", hq_labor_role_edit),
    path("labor/roles/<int:role_id>/toggle/", hq_labor_role_toggle),
    path("labor/rates/", hq_labor_rate_list),
    path("labor/rates/new/", hq_labor_rate_new),
    path("labor/rates/<int:rate_id>/edit/", hq_labor_rate_edit),
    path("labor/rates/<int:rate_id>/toggle/", hq_labor_rate_toggle),
]
