from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.UserSearchView.as_view(), name="list"),
    path("register/", views.SignUpView.as_view(), name="register"),
    path("login/", views.SignInView.as_view(), name="login"),
    path("logout/", views.SignOutView.as_view(), name="logout"),
    path("<int:pk>/badge/", views.UserBadgeAssignView.as_view(), name="assign_badge"),
]
