from django.db import connection
from django.db.models.aggregates import Count
from django.http import JsonResponse
from django.shortcuts import render

from repositories.models import Repository, Visibility


def home(request):
    repositories = (
        Repository.objects
        .filter(visibility=Visibility.PUBLIC)
        .select_related("owner")
        .annotate(star_count=Count("starred_by", distinct=True))
        .order_by("-updated_at")[:12]
    )

    return render(request, "core/home.html", {"repositories": repositories})


def health(request):
    """Liveness/readiness check used by docker compose and the reverse proxy."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "error", "database": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
