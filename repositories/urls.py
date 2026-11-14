from django.urls import path

from . import views

app_name = "repositories"

urlpatterns = [
    path("", views.UserRepositoryListView.as_view(), name="list"),
    path("new/", views.RepositoryCreateView.as_view(), name="create"),
]
