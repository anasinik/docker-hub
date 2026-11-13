from django.urls import path

from . import views

app_name = "repositories"

urlpatterns = [
    path("new/", views.RepositoryCreateView.as_view(), name="create"),
]
