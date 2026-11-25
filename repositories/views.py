import base64
import binascii
import hmac
import json
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate
from django.db.models import Q, Case, Count, IntegerField, Value, When
from django.http import JsonResponse
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.vary import vary_on_headers
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from accounts.identifiers import normalize_login_identifier
from accounts.permissions import RegularUserRequiredMixin
from repositories.services.registry import auth as registry_auth
from repositories.services.registry.base import RegistryError
from repositories.services.registry.events import repositories_to_sync
from repositories.services.registry.factory import get_registry_client
from repositories.services.registry.sync import SyncNotConfiguredError, get_sync_client, sync_repository

from .forms import RepositoryDeleteForm, RepositoryForm, RepositorySettingsForm
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


class RepositorySettingsView(RegularUserRequiredMixin, UpdateView):
    """The owner changes a repository's description and visibility.

    Other users get 404, so a private repository does not reveal that it exists.
    """

    form_class = RepositorySettingsForm
    template_name = "repositories/repository_settings.html"
    context_object_name = "repository"

    def get_queryset(self):
        return Repository.objects.filter(owner=self.request.user).select_related("owner")

    def get_success_url(self):
        return reverse("repositories:detail", args=[self.object.pk])

    def form_valid(self, form):
        response = super().form_valid(form)
        repository = self.object

        logger.info(
            "Repository settings updated: path=%s id=%s visibility=%s",
            repository.registry_path,
            repository.pk,
            repository.visibility,
        )
        messages.success(self.request, f"Repository {repository.registry_path} has been updated.")
        return response


class RepositoryDeleteView(RegularUserRequiredMixin, DeleteView):
    """The owner deletes a repository after typing its name to confirm.

    Its images are deleted from the registry first; stars and tags are deleted
    with it (cascade). If the registry cannot be reached the repository is kept,
    so its images never stay behind for a new repository with the same name.
    Other users get 404, so a private repository does not reveal that it exists.
    """

    form_class = RepositoryDeleteForm
    template_name = "repositories/repository_confirm_delete.html"
    context_object_name = "repository"
    success_url = reverse_lazy("repositories:list")

    def get_queryset(self):
        return Repository.objects.filter(owner=self.request.user).select_related("owner")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["repository"] = self.object
        return kwargs

    def form_valid(self, form):
        path = self.object.registry_path
        repository_id = self.object.pk

        try:
            deleted_manifests = get_registry_client().delete_repository(path)
        except RegistryError as error:
            logger.warning(
                "Registry unavailable, repository not deleted: path=%s id=%s error=%s",
                path,
                repository_id,
                error,
                extra={"repo_id": repository_id},
            )
            messages.error(
                self.request,
                "The container registry is not available, so the images could not be deleted. "
                "The repository was kept; please try again later.",
            )
            return self.render_to_response(self.get_context_data(form=form), status=503)

        response = super().form_valid(form)

        logger.info(
            "Repository deleted: path=%s id=%s manifests=%s",
            path,
            repository_id,
            deleted_manifests,
            extra={"repo_id": repository_id},
        )
        messages.success(self.request, f"Repository {path} has been deleted.")
        return response


@method_decorator(vary_on_headers("HX-Request", "HX-History-Restore-Request"), name="dispatch")
class UserRepositoryListView(RegularUserRequiredMixin, ListView):
    """The logged-in user's own repositories, public and private."""

    template_name = "repositories/repository_list.html"
    context_object_name = "repositories"
    paginate_by = 12
    
    def get_template_names(self):
        is_htmx = self.request.headers.get("HX-Request") == "true"
        is_history_restore = (
            self.request.headers.get("HX-History-Restore-Request") == "true"
        )

        if is_htmx and not is_history_restore:
            return ["repositories/partials/repository_content.html"]

        return [self.template_name]

    def get_queryset(self):
        return (
            Repository.objects
            .filter(owner=self.request.user)
            .select_related("owner")
            .annotate(star_count=Count("starred_by", distinct=True))
            .order_by("-updated_at", "-pk")
        )


@method_decorator(vary_on_headers("HX-Request", "HX-History-Restore-Request"), name="dispatch")
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
            .annotate(star_count=Count("starred_by", distinct=True))
        )

        user = self.request.user

        if user.is_authenticated:
            return queryset.filter(Q(visibility=Visibility.PUBLIC) | Q(owner=user))

        return queryset.filter(visibility=Visibility.PUBLIC)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Tags are synced from the registry on push (RegistryEventsView), so
        # the page does not call the registry.
        context["tags"] = self.object.tags.all()

        user = self.request.user
        context["is_starred"] = (
            user.is_authenticated
            and self.object.starred_by.filter(pk=user.pk).exists()
        )

        return context


def token_error(status, code, description):
    """OAuth2 style error body for the registry token endpoint."""
    response = JsonResponse({"error": code, "error_description": description}, status=status)
    if status == 401:
        response["WWW-Authenticate"] = 'Basic realm="registry"'
    return response


def basic_auth_credentials(request):
    """Return ``(username, password)`` from a Basic Authorization header.

    Returns None when there is no header (anonymous request) and raises
    ValueError when the header is malformed.
    """
    header = request.headers.get("Authorization", "")
    if not header:
        return None
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic":
        raise ValueError("unsupported authorization scheme")
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as error:
        raise ValueError("malformed basic credentials") from error
    username, separator, password = decoded.partition(":")
    if not separator:
        raise ValueError("malformed basic credentials")
    return username, password


@method_decorator(csrf_exempt, name="dispatch")
class RegistryTokenView(View):
    """Token endpoint ("realm") of the container registry.

    * GET: ``docker login`` and anonymous pulls, credentials in a Basic header
      and one ``scope`` parameter per resource.
    * POST: OAuth2 password grant used by containerd for push and pull, with
      space-separated scopes.

    Credentials are checked with ``authenticate()`` after
    ``normalize_login_identifier()``, so ``docker login`` accepts the same
    usernames and emails as the login page. Failed attempts are logged by the
    ``user_login_failed`` signal in accounts. Users who still have to change
    their initial password (``password_change_required``) get no token.
    """

    http_method_names = ["get", "post"]

    def get(self, request):
        try:
            credentials = basic_auth_credentials(request)
        except ValueError:
            return token_error(401, "invalid_client", "Malformed Authorization header.")

        user = None
        if credentials is not None:
            user, error = self.authenticate_user(request, credentials[0], credentials[1])
            if error is not None:
                return error

        return self.token_response(request, user, request.GET.get("service"), request.GET.getlist("scope"))

    def post(self, request):
        if request.POST.get("grant_type") != "password":
            return token_error(400, "unsupported_grant_type", "Only the password grant is supported.")

        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        if not username or not password:
            return token_error(400, "invalid_request", "Username and password are required.")

        user, error = self.authenticate_user(request, username, password)
        if error is not None:
            return error

        return self.token_response(request, user, request.POST.get("service"), request.POST.getlist("scope"))

    def authenticate_user(self, request, identifier, password):
        """Return ``(user, None)``, or ``(None, error response)`` if the user may not get a token."""
        username = normalize_login_identifier(identifier)
        user = authenticate(request, username=username, password=password)
        if user is None:
            return None, token_error(401, "invalid_grant", "Incorrect username or password.")

        if user.password_change_required:
            # The super admin's generated password works only for changing it
            # (issue #34); the web pages enforce this with a middleware.
            logger.warning("Registry login refused, password change required: username=%s", user.username)
            return None, token_error(
                401, "invalid_grant", "Change the initial password on the website before using the registry."
            )
        return user, None

    def token_response(self, request, user, service, scope_values):
        if service and service != settings.REGISTRY_TOKEN_SERVICE:
            return token_error(400, "invalid_request", "Unknown service.")

        scopes = registry_auth.parse_scopes(scope_values)
        access, denied = registry_auth.resolve_access(user, scopes)
        username = user.username if user is not None else ""

        for scope in denied:
            logger.warning(
                "Registry access denied: username=%r scope=%r",
                username or "anonymous",
                f"{scope.type}:{scope.name}:{','.join(scope.actions)}",
            )

        try:
            body = registry_auth.issue_token(username, access)
        except (OSError, ValueError) as error:
            logger.error(
                "Registry token key cannot be loaded: path=%s error=%s",
                settings.REGISTRY_TOKEN_PRIVATE_KEY_PATH,
                error,
            )
            return token_error(503, "temporarily_unavailable", "Registry authentication is not configured.")

        logger.info(
            "Registry token issued: username=%s access=%s",
            username or "anonymous",
            ";".join(f"{item['name']}:{','.join(item['actions'])}" for item in access) or "-",
        )
        return JsonResponse(body)


@method_decorator(csrf_exempt, name="dispatch")
class RegistryEventsView(View):
    """Webhook for registry notifications: syncs the tags of pushed repositories.

    The registry sends ``Authorization: Bearer <REGISTRY_EVENTS_TOKEN>``. Valid
    requests always get 200, also when a sync fails (it is logged): the registry
    would otherwise retry the same events forever. Repeating a request is
    harmless because each sync reads the registry again.
    """

    http_method_names = ["post"]

    def post(self, request):
        expected = settings.REGISTRY_EVENTS_TOKEN
        if not expected:
            logger.error("Registry events received, but REGISTRY_EVENTS_TOKEN is not set")
            return JsonResponse({"error": "Registry events are not configured."}, status=503)

        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(token.encode(), expected.encode()):
            logger.warning("Registry events rejected, invalid token")
            return JsonResponse({"error": "Invalid token."}, status=401)

        try:
            paths = repositories_to_sync(json.loads(request.body))
        except (ValueError, UnicodeDecodeError) as error:
            logger.warning("Registry events rejected, malformed body: error=%s", error)
            return JsonResponse({"error": "Malformed notification."}, status=400)

        try:
            client = get_sync_client()
        except SyncNotConfiguredError as error:
            # 503 so the registry keeps the events and delivers them once fixed
            logger.warning("Registry events not synced: %s", error)
            return JsonResponse({"error": str(error)}, status=503)

        for path, pushed_at in paths.items():
            repository = registry_auth.find_repository(path)
            if repository is None:
                # Pushing to unknown paths is denied (RegistryTokenView), so this
                # is a delete event that arrives after the repository was deleted.
                logger.info("Registry event for unknown repository: path=%r", path)
                continue
            try:
                sync_repository(repository, pushed_at=pushed_at, client=client)
            except RegistryError as error:
                logger.warning(
                    "Registry unavailable, tags not synced: path=%s id=%s error=%s",
                    path,
                    repository.pk,
                    error,
                    extra={"repo_id": repository.pk},
                )
        return JsonResponse({"synced": len(paths)})
