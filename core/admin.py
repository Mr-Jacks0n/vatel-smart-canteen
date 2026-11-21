from django.contrib import admin

from .models import AuditLog, Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "kind", "is_read")
    list_filter = ("kind", "is_read")
    search_fields = ("user__email", "message")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "target_repr")
    list_filter = ("action",)
    search_fields = ("actor__email", "target_repr", "reason")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
