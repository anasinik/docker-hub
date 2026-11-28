from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.UserSearchView.as_view(), name="list"),
    path("register/", views.SignUpView.as_view(), name="register"),
    path("login/", views.SignInView.as_view(), name="login"),
    path("logout/", views.SignOutView.as_view(), name="logout"),
    path("password/", views.AccountPasswordChangeView.as_view(), name="password_change"),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("profile/edit/", views.ProfileUpdateView.as_view(), name="profile_edit"),
    path("admins/", views.AdminListView.as_view(), name="admin_list"),
    path("admins/new/", views.AdminCreateView.as_view(), name="admin_create"),
    path("<int:pk>/badge/", views.UserBadgeAssignView.as_view(), name="assign_badge"),
]
