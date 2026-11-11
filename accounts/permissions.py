"""Role-based access control for views.

Function-based views use the decorators, class-based views use the mixins:

    @admin_required
    def analytics(request): ...

    class OfficialRepositoryCreateView(AdminRequiredMixin, CreateView): ...

Unauthenticated users are redirected to the login page; authenticated users
without a matching role get 403 Forbidden.
"""

from functools import wraps

from django.contrib.auth.mixins import AccessMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from .models import ADMIN_ROLES, Role


def has_role(user, *roles):
    return user.is_authenticated and user.role in roles


def role_required(*roles):
    """Allow the view only to authenticated users with one of ``roles``."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if request.user.role not in roles:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


super_admin_required = role_required(Role.SUPER_ADMIN)
admin_required = role_required(*ADMIN_ROLES)
regular_user_required = role_required(Role.REGULAR_USER)


class RoleRequiredMixin(AccessMixin):
    """Class-based view counterpart of ``role_required``."""

    allowed_roles = ()

    def dispatch(self, request, *args, **kwargs):
        if not has_role(request.user, *self.allowed_roles):
            # AccessMixin redirects anonymous users to login, raises 403 otherwise.
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)


class SuperAdminRequiredMixin(RoleRequiredMixin):
    allowed_roles = (Role.SUPER_ADMIN,)


class AdminRequiredMixin(RoleRequiredMixin):
    allowed_roles = ADMIN_ROLES


class RegularUserRequiredMixin(RoleRequiredMixin):
    allowed_roles = (Role.REGULAR_USER,)
