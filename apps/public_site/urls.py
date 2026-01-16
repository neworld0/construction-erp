from django.urls import path

from . import views

urlpatterns = [
    path("", views.home),
    path("about/", views.about),
    path("projects/", views.projects_list),
    path("projects/<slug:slug>/", views.projects_detail),
    path("partners/", views.partners),
    path("contact/", views.contact),
]
