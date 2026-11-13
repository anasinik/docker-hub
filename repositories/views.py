import logging

from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import CreateView, ListView

from accounts.permissions import RegularUserRequiredMixin

from .forms import RepositoryForm
from .models import Repository, Visibility

logger = logging.getLogger(__name__)


class RepositoryCreateView(RegularUserRequiredMixin, CreateView):
    """Regular users create their own repositories.

    Admins get 403: they manage official repositories instead (issue #28).
    """

    model = Repository
    form_class = RepositoryForm
    template_name = "repositories/repository_form.html"
    success_url = reverse_lazy("core:home")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["owner"] = self.request.user
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        repository = self.object

        logger.info(
            "Repository created: path=%s id=%s visibility=%s",
            repository.registry_path,
            repository.pk,
            repository.visibility,
        )
        messages.success(self.request, f"Repository {repository.registry_path} has been created.")
        return response


class RepositoryListView(ListView):
    model = Repository
    template_name = "repositories/repository_list.html"
    context_object_name = "repositories"

    def get_queryset(self):
        return (
            Repository.objects
            .select_related("owner")
            .filter(visibility=Visibility.PUBLIC)
            .order_by("-updated_at")
        )