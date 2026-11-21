from django.contrib import admin

from .models import AnnualPass, Wallet, WalletTransaction


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ("user", "balance", "debit_frequency", "auto_debit_enabled")
    list_filter = ("debit_frequency", "auto_debit_enabled")
    search_fields = ("user__email", "user__first_name", "user__last_name")
    readonly_fields = ("balance",)


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    """Journal immuable en lecture seule dans l'administration Django."""

    list_display = (
        "created_at",
        "wallet",
        "kind",
        "direction",
        "amount",
        "balance_after",
        "created_by",
    )
    list_filter = ("kind", "direction")
    search_fields = ("wallet__user__email", "reason")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AnnualPass)
class AnnualPassAdmin(admin.ModelAdmin):
    list_display = ("student", "school_year", "valid_from", "valid_until", "status")
    list_filter = ("status", "school_year")
    search_fields = ("student__email", "student__first_name", "student__last_name")
