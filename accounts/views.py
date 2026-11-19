import logging

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import FormView

from .forms import LoginForm, SignUpForm
from .models import Role

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
