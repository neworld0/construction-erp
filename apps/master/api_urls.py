from django.urls import path

from .api_views import CbsFavoriteToggleView, CbsFavoritesView, CbsSearchView

urlpatterns = [
    path("master/cbs/search", CbsSearchView.as_view()),
    path("master/cbs/favorites", CbsFavoritesView.as_view()),
    path("master/cbs/favorites/toggle", CbsFavoriteToggleView.as_view()),
]
