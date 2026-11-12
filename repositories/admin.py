from django.contrib import admin

from .models import Repository


@admin.register(Repository)
class RepositoryAdmin(admin.ModelAdmin):
    list_display = ("registry_path", "owner", "visibility", "is_official", "created_at")
    list_filter = ("visibility", "is_official")
    search_fields = ("name", "owner__username", "description")
    list_select_related = ("owner",)
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Repository", ordering="name")
    def registry_path(self, obj):
        return obj.registry_path
