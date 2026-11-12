import logging

from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import FormView

from .forms import SignUpForm
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
