import logging

from django.contrib import messages
from django.db.models import Q
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.vary import vary_on_headers
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

@method_decorator(vary_on_headers("HX-Request", "HX-History-Restore-Request"), name="dispatch",)
class RepositoryListView(ListView):
    model = Repository
    template_name = "repositories/repository_search.html"
    context_object_name = "repositories"
    paginate_by = 12
    
    def get_template_names(self):
        is_htmx = self.request.headers.get("HX-Request") == "true"
        is_history_restore = self.request.headers.get("HX-History-Restore-Request") == "true"

        if is_htmx and not is_history_restore:
            return ["repositories/partials/search_content.html"]

        return [self.template_name]
    
    def get_queryset(self):
        queryset = (
            Repository.objects
            .filter(visibility=Visibility.PUBLIC)
            .select_related("owner")
        )

        query = self.request.GET.get("q", "").strip()

        if query:
            queryset = queryset.filter(
                Q(name__icontains=query)
                | Q(description__icontains=query)
                | Q(owner__username__icontains=query)
            )

        official = self.request.GET.get("official")

        if official == "1":
            queryset = queryset.filter(is_official=True)
        elif official == "0":
            queryset = queryset.filter(is_official=False)

        badge = self.get_selected_badges()

        if badge:
            queryset = queryset.filter(owner__badge=badge)

        return queryset.order_by("-updated_at", "-pk")
            
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        query_params = self.request.GET.copy()
        query_params.pop("page", None)

        context["querystring"] = query_params.urlencode()
        context["selected_badges"] = self.get_selected_badges()

        return context
    
    def get_selected_badges(self):
        allowed_badges = { "VERIFIED_PUBLISHER", "SPONSORED_OSS" }

        return [
            badge
            for badge in self.request.GET.getlist("badge")
            if badge in allowed_badges
        ]