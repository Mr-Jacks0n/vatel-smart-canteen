from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import diner_required
from menus.models import Dish, MealOption, MealService
from menus.services import group_options_by_category
from payments.models import Payment
from payments.services import create_payment
from wallet.models import Wallet
from wallet.services import get_projected_balance, has_active_pass

from .models import Reservation
from .services import (
    cancel_reservation,
    decline_day,
    detect_allergen_conflicts,
    generate_qr_svg,
    modify_reservation,
    pay_now_scheduled,
    reserve,
)


@diner_required
def reservation_list_view(request):
    today = timezone.localdate()
    qs = (
        Reservation.objects.filter(beneficiary=request.user)
        .select_related("service")
        .prefetch_related("items__option__dish")
    )
    upcoming = [r for r in qs if r.service.date >= today]
    past = [r for r in qs if r.service.date < today]
    return render(
        request,
        "reservations/list.html",
        {
            "upcoming": upcoming,
            "past": past,
            "now": timezone.now(),
        },
    )


@diner_required
def compose_meal_view(request, service_id: int):
    service = get_object_or_404(MealService, pk=service_id, is_published=True)
    modify_id = request.GET.get("modifier") or request.POST.get("modify_id")
    existing_res = None
    if modify_id:
        existing_res = get_object_or_404(
            Reservation,
            pk=modify_id,
            beneficiary=request.user,
            service=service,
        )

    grouped = group_options_by_category(service)
    wallet, _ = Wallet.objects.get_or_create(user=request.user)
    active_pass = has_active_pass(request.user, on_date=service.date)
    projected_balance = get_projected_balance(wallet)

    allergen_conflicts = []

    if request.method == "POST":
        entree_id = request.POST.get("entree_id")
        plat_id = request.POST.get("plat_id")
        dessert_id = request.POST.get("dessert_id")
        option_ids = [
            int(v) for v in (entree_id, plat_id, dessert_id) if v and v.isdigit()
        ]
        skip_starter = not bool(entree_id)
        skip_dessert = not bool(dessert_id)
        extra_portions = int(request.POST.get("extra_portions") or 0)
        fulfillment = request.POST.get("fulfillment", Reservation.Fulfillment.ON_SITE)
        delivery_location = request.POST.get("delivery_location", "")
        payment_mode_choice = request.POST.get(
            "payment_mode", Reservation.PaymentMode.WALLET
        )
        allergy_acknowledged = request.POST.get("allergy_acknowledged") == "on"

        selected_options = list(
            MealOption.objects.filter(pk__in=option_ids).prefetch_related("dish__allergens")
        )
        allergen_conflicts = detect_allergen_conflicts(request.user, selected_options)

        try:
            kwargs = {
                "option_ids": option_ids,
                "skip_starter": skip_starter,
                "skip_dessert": skip_dessert,
                "extra_portions": extra_portions,
                "fulfillment": fulfillment,
                "delivery_location": delivery_location,
                "payment_mode_choice": payment_mode_choice,
                "allergy_acknowledged": allergy_acknowledged,
            }
            if existing_res:
                res = modify_reservation(request.user, existing_res.pk, **kwargs)
                messages.success(request, "Votre réservation a été modifiée.")
            else:
                res = reserve(request.user, service.pk, **kwargs)
                messages.success(
                    request,
                    f"Repas réservé pour le {service.date:%d/%m/%Y} (code {res.short_code}).",
                )
            return redirect("reservations:ticket", ticket_token=res.ticket_token)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))

    return render(
        request,
        "reservations/compose.html",
        {
            "service": service,
            "existing_res": existing_res,
            "entrees": grouped.get(Dish.Category.ENTREE, []),
            "plats": grouped.get(Dish.Category.PLAT, []),
            "desserts": grouped.get(Dish.Category.DESSERT, []),
            "active_pass": active_pass,
            "wallet": wallet,
            "projected_balance": projected_balance,
            "delivery_enabled": getattr(settings, "DELIVERY_ENABLED", True),
            "delivery_fee": getattr(settings, "DELIVERY_FEE", 500),
            "pickup_enabled": getattr(settings, "PICKUP_PAYMENT_ENABLED", True),
            "max_extra_portions": getattr(settings, "MAX_EXTRA_PORTIONS", 1),
            "allergen_conflicts": allergen_conflicts,
        },
    )


@diner_required
def compose_price_preview_view(request, service_id: int):
    """Calcul HTMX en direct du total du repas."""
    service = get_object_or_404(MealService, pk=service_id, is_published=True)
    extra_portions = int(request.GET.get("extra_portions") or 0)
    fulfillment = request.GET.get("fulfillment", Reservation.Fulfillment.ON_SITE)
    active_pass = has_active_pass(request.user, on_date=service.date)

    extra_cost = extra_portions * (service.extra_portion_price or 0)
    delivery_cost = (
        int(getattr(settings, "DELIVERY_FEE", 500))
        if fulfillment == Reservation.Fulfillment.DELIVERY
        and getattr(settings, "DELIVERY_ENABLED", True)
        else 0
    )
    total = service.meal_price + extra_cost + delivery_cost
    due_pass = extra_cost + delivery_cost
    return render(
        request,
        "reservations/partials/price_summary.html",
        {
            "service": service,
            "extra_portions": extra_portions,
            "extra_cost": extra_cost,
            "delivery_cost": delivery_cost,
            "total": total,
            "active_pass": active_pass,
            "due_pass": due_pass,
        },
    )


@diner_required
@require_POST
def decline_day_view(request, service_id: int):
    try:
        decline_day(request.user, service_id)
        messages.info(request, "Votre choix « Je ne mange pas ce jour » a été enregistré.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("menus:week_menu")


@diner_required
@require_POST
def cancel_reservation_view(request, reservation_id: int):
    reservation = get_object_or_404(
        Reservation, pk=reservation_id, beneficiary=request.user
    )
    try:
        cancel_reservation(request.user, reservation.pk)
        messages.success(request, "Votre réservation a été annulée.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("reservations:list")


@diner_required
def ticket_view(request, ticket_token: str):
    """Ticket QR plein écran — filtré par bénéficiaire (renvoie 404 sinon)."""
    reservation = get_object_or_404(
        Reservation.objects.select_related("service").prefetch_related("items__option__dish"),
        ticket_token=ticket_token,
        beneficiary=request.user,
    )
    validation_url = request.build_absolute_uri(
        reverse("canteen:validate_qr", kwargs={"ticket_token": reservation.ticket_token})
    )
    qr_svg = generate_qr_svg(validation_url)
    pickup_methods = [
        (Payment.Method.WAVE, "Wave (Mobile Money)"),
        (Payment.Method.ORANGE_MONEY, "Orange Money"),
        (Payment.Method.MTN_MOMO, "MTN MoMo"),
        (Payment.Method.MOOV_MONEY, "Moov Money"),
        (Payment.Method.BANK_CARD, "Carte bancaire"),
    ]
    return render(
        request,
        "reservations/ticket.html",
        {
            "reservation": reservation,
            "qr_svg": qr_svg,
            "pickup_methods": pickup_methods,
        },
    )


@diner_required
@require_POST
def init_pickup_payment_view(request, reservation_id: int):
    reservation = get_object_or_404(
        Reservation, pk=reservation_id, beneficiary=request.user
    )
    method = request.POST.get("method", Payment.Method.WAVE)
    phone_number = request.POST.get("phone_number", "")
    try:
        payment = create_payment(
            kind=Payment.Kind.PICKUP,
            beneficiary=request.user,
            payer=request.user,
            method=method,
            phone_number=phone_number,
            reservation=reservation,
        )
        return redirect("payments:simulate", reference=payment.reference)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("reservations:ticket", ticket_token=reservation.ticket_token)


@diner_required
@require_POST
def pay_now_scheduled_view(request):
    try:
        settled = pay_now_scheduled(request.user)
        messages.success(
            request,
            f"{len(settled)} repas programmé(s) réglé(s) depuis votre Solde Vatel Cantine.",
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("wallet:home")


@diner_required
def multi_reserve_view(request):
    """Réservation de plusieurs jours en une opération."""
    from menus.services import get_week_services
    from .services import reserve_multiple_days

    now = timezone.now()
    services = [
        s
        for s in get_week_services(published_only=True)
        if s.reservation_deadline > now
    ]
    existing_service_ids = set(
        Reservation.objects.filter(
            beneficiary=request.user,
            service__in=services,
        )
        .exclude(status=Reservation.Status.CANCELLED)
        .values_list("service_id", flat=True)
    )
    open_services = [s for s in services if s.id not in existing_service_ids]

    if request.method == "POST":
        selected_ids = request.POST.getlist("service_ids")
        allergy_ack = request.POST.get("allergy_acknowledged") == "on"
        selections = []
        for sid in selected_ids:
            if not sid.isdigit():
                continue
            sid_int = int(sid)
            entree_id = request.POST.get(f"entree_{sid_int}")
            plat_id = request.POST.get(f"plat_{sid_int}")
            dessert_id = request.POST.get(f"dessert_{sid_int}")
            opt_ids = [
                int(v)
                for v in (entree_id, plat_id, dessert_id)
                if v and v.isdigit()
            ]
            selections.append(
                {
                    "service_id": sid_int,
                    "option_ids": opt_ids,
                    "skip_starter": not bool(entree_id),
                    "skip_dessert": not bool(dessert_id),
                    "allergy_acknowledged": allergy_ack,
                }
            )
        try:
            created = reserve_multiple_days(request.user, selections)
            messages.success(
                request,
                f"{len(created)} repas réservé(s) en une seule opération !",
            )
            return redirect("reservations:list")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))

    open_days = []
    for svc in open_services:
        grouped = group_options_by_category(svc)
        open_days.append(
            {
                "service": svc,
                "entrees": grouped.get(Dish.Category.ENTREE, []),
                "plats": grouped.get(Dish.Category.PLAT, []),
                "desserts": grouped.get(Dish.Category.DESSERT, []),
            }
        )

    return render(
        request,
        "reservations/multi_reserve.html",
        {"open_days": open_days},
    )


@diner_required
@require_POST
def rate_reservation_view(request, reservation_id: int):
    """Notation d'un plat après service (1 à 5)."""
    from .services import rate_reservation_dish

    get_object_or_404(Reservation, pk=reservation_id, beneficiary=request.user)
    try:
        rating = rate_reservation_dish(
            request.user, reservation_id, request.POST.get("score")
        )
        messages.success(request, f"Merci ! Votre note ({rating.score}/5) a été enregistrée.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("reservations:list")
