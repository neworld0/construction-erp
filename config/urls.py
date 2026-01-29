"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from two_factor import urls as two_factor_urls

from apps.core.views import healthz_view

urlpatterns = [
    path('admin/', admin.site.urls),
    path("", include("apps.core.urls")),
    path("", include("apps.public_site.urls")),
    path(
        "",
        include((two_factor_urls.urlpatterns[0], "two_factor"), namespace="two_factor"),
    ),
    path("healthz/", healthz_view),
    path("", include("apps.ceo.web_urls")),
    path("app/", include("apps.core.app_urls")),
    path("api/", include("apps.projects.urls")),
    path("api/", include("apps.cost.urls")),
    path("api/", include("apps.field.urls")),
    path("api/", include("apps.finance.urls")),
    path("api/", include("apps.schedule.urls")),
    path("api/", include("apps.contracts.urls")),
    path("api/", include("apps.evidence.urls")),
    path("api/", include("apps.risk.urls")),
    path("api/", include("apps.ceo.urls")),
    path("api/", include("apps.audit.urls")),
    path("api/", include("apps.master.api_urls")),
    path("api/closing/", include("apps.closing.urls")),
    path("api/kpi/", include("apps.kpi.urls")),
    path("api/inventory/", include("apps.inventory.urls")),
    path("api/labor/", include("apps.labor.urls")),
]
