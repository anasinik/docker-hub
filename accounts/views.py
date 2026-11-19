import logging

from django.contrib import messages
from django.contrib.auth import login
from django.db.models import Q, Case, IntegerField, Value, When
from django.utils.decorators import method_decorator
from django.views.decorators.vary import vary_on_headers
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import FormView, ListView

from accounts.permissions import AdminRequiredMixin

from .forms import LoginForm, SignUpForm
from .models import Badge, Role, User

logger = logging.getLogger(__name__)


class SignUpView(FormView):
    template_name = "accounts/register.html"
    form_class = SignUpForm
    success_url = reverse_lazy("core:home")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(self.success_url)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save(commit=False)
        user.role = Role.REGULAR_USER
        user.save()

        login(self.request, user)
        logger.info("User registered: username=%s id=%s", user.username, user.pk)
        messages.success(self.request, f"Welcome, {user.username}! Your account has been created.")
        return super().form_valid(form)


class SignInView(LoginView):
    """Sign in with username or email.

    After signing in, the user is sent to the safe ``next`` URL if there is one
    (external URLs are ignored), otherwise to ``LOGIN_REDIRECT_URL``. Signed-in
    users who open the page are redirected the same way.
    """

    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class SignOutView(LogoutView):
    """Sign out. Only POST is accepted, so other sites cannot log users out with a link."""

    def post(self, request, *args, **kwargs):
        was_authenticated = request.user.is_authenticated
        response = super().post(request, *args, **kwargs)
        if was_authenticated:
            messages.info(request, "You have been signed out.")
        return response

@method_decorator(vary_on_headers("HX-Request", "HX-History-Restore-Request"), name="dispatch")
class UserSearchView(AdminRequiredMixin, ListView):
    """Administrators search for regular users."""

    template_name = "accounts/user_search.html"
    context_object_name = "users"
    paginate_by = 12

    def get_template_names(self):
        is_htmx = self.request.headers.get("HX-Request") == "true"
        is_history_restore = self.request.headers.get("HX-History-Restore-Request") == "true"

        if is_htmx and not is_history_restore:
            return ["accounts/partials/user_search_content.html"]

        return [self.template_name]

    def get_queryset(self):
        queryset = User.objects.filter(role=Role.REGULAR_USER)
        selected_badges = self.request.GET.getlist("badge")

        if selected_badges:
            queryset = queryset.filter(badge__in=selected_badges)

        query = self.request.GET.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(username__icontains=query) | Q(email__icontains=query)
            ).annotate(
                text_score=Case(
                    When(username__iexact=query, then=Value(100)),
                    When(username__istartswith=query, then=Value(80)),
                    When(username__icontains=query, then=Value(60)),
                    When(email__iexact=query, then=Value(50)),
                    When(email__icontains=query, then=Value(40)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            )

            return queryset.order_by("-text_score", "-date_joined", "-pk")
        return queryset.order_by("-date_joined", "-pk")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        query_params = self.request.GET.copy()
        query_params.pop("page", None)

        context["querystring"] = query_params.urlencode()
        context["selected_badges"] = self.request.GET.getlist("badge")

        return context