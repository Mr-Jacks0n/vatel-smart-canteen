from django.contrib import admin

from .models import Reservation, ReservationItem


class ReservationItemInline(admin.TabularInline):
    model = ReservationItem
    extra = 0
    readonly_fields = ("option", "category", "portions")


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = (
        "service",
        "beneficiary",
        "status",
        "payment_mode",
        "payment_status",
        "total_price",
        "amount_due_at_pickup",
        "short_code",
    )
    list_filter = ("status", "payment_mode", "payment_status", "fulfillment")
    search_fields = ("beneficiary__email", "short_code", "ticket_token")
    inlines = [ReservationItemInline]
