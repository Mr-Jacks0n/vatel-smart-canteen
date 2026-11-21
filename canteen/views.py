import csv
from datetime import date

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import equipe_required
from menus.models import MealService
from reservations.models import Reservation

from .closure import trigger_pending_closures_if_needed
from .services import (
    get_deliveries_by_location,
    get_kitchen_consolidation,
    serve_reservation,
)


@equipe_required
def kitchen_view(request):
    trigger_pending_closures_if_needed()
    services = MealService.objects.filter(is_published=True).order_by("-date")[:15]
    selected_date = request.GET.get("date")
    service = None
    if selected_date:
        try:
            service = MealService.objects.filter(date=date.fromisoformat(selected_date)).first()
        except ValueError:
            service = None
    if not service:
        today = timezone.localdate()
        service = (
            MealService.objects.filter(is_published=True, date__gte=today).order_by("date").first()
            or services.first()
        )

    consolidation = get_kitchen_consolidation(service) if service else None
    return render(
        request,
        "canteen/kitchen.html",
        {
            "services": services,
            "selected_service": service,
            "consolidation": consolidation,
        },
    )


@equipe_required
def counter_view(request):
    trigger_pending_closures_if_needed()
    today = timezone.localdate()
    short_code = (request.GET.get("code") or "").strip().upper()
    reservation = None
    lookup_error = ""

    if short_code:
        reservation = (
            Reservation.objects.select_related("service", "beneficiary")
            .prefetch_related("items__option__dish")
            .filter(service__date=today, short_code=short_code)
            .first()
        )
        if not reservation:
            lookup_error = f"Aucun ticket trouvé aujourd'hui pour le code « {short_code} »."

    recent_served = (
        Reservation.objects.filter(
            service__date=today, status=Reservation.Status.SERVED
        )
        .select_related("beneficiary", "served_by")
        .order_by("-served_at")[:15]
    )
    return render(
        request,
        "canteen/counter.html",
        {
            "short_code": short_code,
            "reservation": reservation,
            "lookup_error": lookup_error,
            "recent_served": recent_served,
        },
    )


@equipe_required
def validate_qr_view(request, ticket_token: str):
    """Page de confirmation avant validation en POST."""
    trigger_pending_closures_if_needed()
    reservation = get_object_or_404(
        Reservation.objects.select_related("service", "beneficiary").prefetch_related(
            "items__option__dish"
        ),
        ticket_token=ticket_token,
    )
    return render(
        request,
        "canteen/counter.html",
        {
            "short_code": reservation.short_code or "",
            "reservation": reservation,
            "lookup_error": "",
            "recent_served": Reservation.objects.filter(
                service__date=timezone.localdate(), status=Reservation.Status.SERVED
            )
            .select_related("beneficiary", "served_by")
            .order_by("-served_at")[:10],
        },
    )


@equipe_required
@require_POST
def serve_ticket_view(request, reservation_id: int):
    reservation = get_object_or_404(Reservation, pk=reservation_id)
    try:
        served = serve_reservation(reservation.pk, actor=request.user)
        verb = "Livré" if served.fulfillment == Reservation.Fulfillment.DELIVERY else "Servi"
        messages.success(
            request,
            f"Ticket {served.short_code} ({served.beneficiary.full_name}) : {verb} avec succès !",
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    next_page = request.POST.get("next")
    if next_page == "deliveries":
        return redirect("canteen:deliveries")
    return redirect("canteen:counter")


@equipe_required
def deliveries_view(request):
    trigger_pending_closures_if_needed()
    today = timezone.localdate()
    service = MealService.objects.filter(date=today).first()
    grouped_deliveries = get_deliveries_by_location(service) if service else []
    return render(
        request,
        "canteen/deliveries.html",
        {
            "service": service,
            "grouped_deliveries": grouped_deliveries,
        },
    )


def _safe_csv_cell(value):
    text = str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{text}"
    return text


@equipe_required
def kitchen_export_csv_view(request):
    """Export CSV de la consolidation cuisine."""
    trigger_pending_closures_if_needed()
    selected_date = request.GET.get("date")
    service = None
    if selected_date:
        try:
            service = MealService.objects.filter(date=date.fromisoformat(selected_date)).first()
        except ValueError:
            service = None
    if not service:
        service = (
            MealService.objects.filter(is_published=True, date__gte=timezone.localdate())
            .order_by("date")
            .first()
            or MealService.objects.filter(is_published=True).order_by("-date").first()
        )
    if not service:
        messages.error(request, "Aucun service disponible pour l'export CSV.")
        return redirect("canteen:kitchen")

    consolidation = get_kitchen_consolidation(service)
    response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
    response["Content-Disposition"] = (
        f'attachment; filename="consolidation-cuisine-{service.date.isoformat()}.csv"'
    )
    writer = csv.writer(response, delimiter=";")
    writer.writerow(["Catégorie", "Plat / Indicateur", "Quantité"])
    for cat_label, rows in consolidation["by_category"]:
        for row in rows:
            writer.writerow(
                [
                    _safe_csv_cell(cat_label),
                    _safe_csv_cell(row["dish_name"]),
                    row["portions"],
                ]
            )
    writer.writerow([])
    writer.writerow(["Synthèse", "Repas prévus", consolidation["total_meals"]])
    writer.writerow(["Synthèse", "Portions supplémentaires", consolidation["extra_portions_count"]])
    writer.writerow(["Synthèse", "Sans entrée", consolidation["skip_starter_count"]])
    writer.writerow(["Synthèse", "Sans dessert", consolidation["skip_dessert_count"]])
    writer.writerow(["Synthèse", "Je ne mange pas ce jour", consolidation["declined_count"]])
    writer.writerow(["Synthèse", "Sans réponse", consolidation["no_response_count"]])
    return response
