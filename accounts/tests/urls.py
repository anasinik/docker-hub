"""URLs used only by the permission tests, to exercise the decorators and mixins."""

from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path
from django.views import View

from accounts.permissions import (
    AdminRequiredMixin,
    RegularUserRequiredMixin,
    SuperAdminRequiredMixin,
    admin_required,
    regular_user_required,
    super_admin_required,
)


def ok(request):
    return HttpResponse("ok")


class OkView(View):
    def get(self, request):
        return HttpResponse("ok")


class SuperAdminView(SuperAdminRequiredMixin, OkView):
    pass


class AdminView(AdminRequiredMixin, OkView):
    pass


class RegularUserView(RegularUserRequiredMixin, OkView):
    pass


urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("fbv/super-admin/", super_admin_required(ok), name="fbv-super-admin"),
    path("fbv/admin/", admin_required(ok), name="fbv-admin"),
    path("fbv/regular-user/", regular_user_required(ok), name="fbv-regular-user"),
    path("cbv/super-admin/", SuperAdminView.as_view(), name="cbv-super-admin"),
    path("cbv/admin/", AdminView.as_view(), name="cbv-admin"),
    path("cbv/regular-user/", RegularUserView.as_view(), name="cbv-regular-user"),
]
