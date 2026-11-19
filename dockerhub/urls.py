"""URL configuration for the dockerhub project."""

from django.contrib import admin
from django.urls import include, path

from repositories.views import RepositoryListView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("repositories/", include("repositories.urls")),
    path("search/", RepositoryListView.as_view(), name="repository_search"),
    path("", include("core.urls")),
]
