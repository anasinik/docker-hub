import logging
from shutil import RegistryError

from django.contrib import messages
from django.db.models import Q, Case, Count, IntegerField, Value, When
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.vary import vary_on_headers
from django.views.generic import CreateView, DetailView, ListView

from accounts.permissions import RegularUserRequiredMixin
from repositories.services.registry.factory import get_registry_client

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
    success_url = reverse_lazy("repositories:list")

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


class UserRepositoryListView(RegularUserRequiredMixin, ListView):
    """The logged-in user's own repositories, public and private."""

    template_name = "repositories/repository_list.html"
    context_object_name = "repositories"
    paginate_by = 12

    def get_queryset(self):
        return (
            Repository.objects
            .filter(owner=self.request.user)
            .select_related("owner")
            .annotate(star_count=Count("starred_by", distinct=True))
            .order_by("-updated_at", "-pk")
        )


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
            .annotate(star_count=Count("starred_by", distinct=True))
        )

        official = self.request.GET.get("official")

        if official == "1":
            queryset = queryset.filter(is_official=True)
        elif official == "0":
            queryset = queryset.filter(is_official=False)

        selected_badges = self.request.GET.getlist("badge")

        if selected_badges:
            queryset = queryset.filter(owner__badge__in=selected_badges)

        query = self.request.GET.get("q", "").strip()

        if query:
            queryset = queryset.filter(
                Q(name__icontains=query)
                | Q(description__icontains=query)
                | Q(owner__username__icontains=query)
            ).annotate(
                text_score=Case(
                    When(name__iexact=query, then=Value(100)),
                    When(name__istartswith=query, then=Value(80)),
                    When(name__icontains=query, then=Value(60)),
                    When(owner__username__icontains=query, then=Value(40)),
                    When(description__icontains=query, then=Value(20)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            )

            return queryset.order_by("-text_score", "-star_count", "-updated_at", "-pk")
        return queryset.order_by("-star_count", "-updated_at", "-pk")
                                
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        query_params = self.request.GET.copy()
        query_params.pop("page", None)

        context["querystring"] = query_params.urlencode()
        context["selected_badges"] = self.request.GET.getlist("badge")

        return context
    
class RepositoryDetailView(DetailView):
    model = Repository
    template_name = "repositories/repository_detail.html"
    context_object_name = "repository"

    def get_queryset(self):
        queryset = (
            Repository.objects
            .select_related("owner")
            .annotate(
                star_count=Count("starred_by", distinct=True)
            )
        )

        user = self.request.user

        if user.is_authenticated:
            return queryset.filter(
                Q(visibility=Visibility.PUBLIC)
                | Q(owner=user)
            )

        return queryset.filter(visibility=Visibility.PUBLIC)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        try:
            context["tags"] = get_registry_client().list_tags(self.object)
            context["registry_unavailable"] = False
        except RegistryError:
            context["tags"] = []
            context["registry_unavailable"] = True

        user = self.request.user
        context["is_starred"] = (
            user.is_authenticated
            and self.object.starred_by.filter(pk=user.pk).exists()
        )

        return context