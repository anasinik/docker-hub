"""URL configuration for the dockerhub project."""

from django.contrib import admin
from django.urls import include, path

from repositories.views import RegistryTokenView, RepositoryListView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("repositories/", include("repositories.urls")),
    path("search/", RepositoryListView.as_view(), name="repository_search"),
    path("registry/token/", RegistryTokenView.as_view(), name="registry_token"),
    path("", include("core.urls")),
]
