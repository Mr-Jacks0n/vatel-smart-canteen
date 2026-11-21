from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    """Paiements en lecture seule dans l'administration Django."""

    list_display = (
        "reference",
        "kind",
        "beneficiary",
        "payer",
        "method",
        "amount",
        "status",
        "created_at",
    )
    list_filter = ("kind", "method", "status")
    search_fields = ("reference", "beneficiary__email", "payer__email")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
