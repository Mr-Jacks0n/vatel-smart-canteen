"""Services métier de l'espace équipe : consolidation cuisine et validation comptoir/livraison."""

from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.models import DietaryProfile, User
from core.services import log_sensitive_action
from menus.models import Dish, MealService
from reservations.models import Reservation, ReservationItem


def get_kitchen_consolidation(service: MealService) -> dict:
    """Calcule les portions par plat/catégorie, Sans entrée/dessert, Je ne mange pas, sans réponse et allergies du jour."""
    active_reservations = list(
        Reservation.objects.filter(
            service=service,
            status__in=[Reservation.Status.CONFIRMED, Reservation.Status.SERVED],
        )
        .select_related("beneficiary")
        .prefetch_related("items__option__dish")
    )
    declined_count = Reservation.objects.filter(
        service=service, status=Reservation.Status.DECLINED
    ).count()

    total_diners = User.objects.filter(
        role__in=[User.Role.ELEVE, User.Role.PERSONNEL], is_active=True
    ).count()
    responded_count = len(active_reservations) + declined_count
    no_response_count = max(0, total_diners - responded_count)

    skip_starter_count = sum(1 for r in active_reservations if r.skip_starter)
    skip_dessert_count = sum(1 for r in active_reservations if r.skip_dessert)
    extra_portions_count = sum(r.extra_portions for r in active_reservations)

    # Portions consolidées par plat et par catégorie
    item_totals = (
        ReservationItem.objects.filter(
            reservation__service=service,
            reservation__status__in=[
                Reservation.Status.CONFIRMED,
                Reservation.Status.SERVED,
            ],
        )
        .values("category", "option__dish__name")
        .annotate(total_portions=Sum("portions"))
        .order_by("category", "option__dish__name")
    )
    by_category = {
        Dish.Category.ENTREE: [],
        Dish.Category.PLAT: [],
        Dish.Category.DESSERT: [],
    }
    for row in item_totals:
        by_category.setdefault(row["category"], []).append(
            {
                "dish_name": row["option__dish__name"],
                "portions": row["total_portions"],
            }
        )

    # Allergies et intolérances du jour associées au code court du ticket
    beneficiary_ids = [r.beneficiary_id for r in active_reservations]
    profiles = {
        p.user_id: p
        for p in DietaryProfile.objects.filter(user_id__in=beneficiary_ids).prefetch_related(
            "allergies", "intolerances"
        )
    }
    allergy_alerts = []
    for res in active_reservations:
        prof = profiles.get(res.beneficiary_id)
        if not prof:
            continue
        allergies = list(prof.allergies.values_list("name", flat=True))
        intolerances = list(prof.intolerances.values_list("name", flat=True))
        if allergies or intolerances:
            allergy_alerts.append(
                {
                    "short_code": res.short_code,
                    "beneficiary": res.beneficiary.full_name,
                    "allergies": allergies,
                    "intolerances": intolerances,
                    "acknowledged": res.allergy_acknowledged,
                }
            )

    return {
        "service": service,
        "total_meals": len(active_reservations),
        "declined_count": declined_count,
        "no_response_count": no_response_count,
        "skip_starter_count": skip_starter_count,
        "skip_dessert_count": skip_dessert_count,
        "extra_portions_count": extra_portions_count,
        "by_category": [
            ("Entrées", by_category[Dish.Category.ENTREE]),
            ("Plats principaux", by_category[Dish.Category.PLAT]),
            ("Desserts", by_category[Dish.Category.DESSERT]),
        ],
        "allergy_alerts": allergy_alerts,
    }


def get_deliveries_by_location(service: MealService) -> list[tuple[str, list[Reservation]]]:
    deliveries = (
        Reservation.objects.filter(
            service=service,
            fulfillment=Reservation.Fulfillment.DELIVERY,
            status__in=[Reservation.Status.CONFIRMED, Reservation.Status.SERVED],
        )
        .select_related("beneficiary")
        .prefetch_related("items__option__dish")
        .order_by("delivery_location", "short_code")
    )
    grouped = defaultdict(list)
    for res in deliveries:
        grouped[res.delivery_location or "Non précisé"].append(res)
    return sorted(grouped.items(), key=lambda item: item[0])


@transaction.atomic
def serve_reservation(reservation_id: int, actor: User) -> Reservation:
    """Validation atomique de la remise d'un plateau au comptoir ou à la livraison."""
    if actor.role not in (User.Role.EQUIPE, User.Role.ADMIN):
        raise ValidationError("Seule l'équipe cantine ou un administrateur peut valider un ticket.")

    res = (
        Reservation.objects.select_for_update()
        .select_related("service", "beneficiary")
        .get(pk=reservation_id)
    )

    if res.status == Reservation.Status.SERVED:
        verb = "livré" if res.fulfillment == Reservation.Fulfillment.DELIVERY else "servi"
        served_time = timezone.localtime(res.served_at).strftime("%H:%M") if res.served_at else "—"
        raise ValidationError(f"Ticket déjà {verb} à {served_time}.")

    if res.status == Reservation.Status.CANCELLED:
        raise ValidationError("Ticket refusé : cette réservation a été annulée.")

    if res.status == Reservation.Status.DECLINED:
        raise ValidationError("Ticket refusé : cet utilisateur a déclaré ne pas manger ce jour.")

    today = timezone.localdate()
    if res.service.date != today:
        raise ValidationError(
            f"Ticket valable uniquement le jour du service ({res.service.date:%d/%m/%Y})."
        )

    if res.amount_due_at_pickup > 0 or res.payment_status != Reservation.PaymentStatus.SETTLED:
        raise ValidationError(
            f"Paiement requis avant remise : {res.amount_due_at_pickup} FCFA à régler dans l'application (Mobile Money ou carte)."
        )

    res.status = Reservation.Status.SERVED
    res.served_at = timezone.now()
    res.served_by = actor
    res.save(update_fields=["status", "served_at", "served_by"])

    log_sensitive_action(
        actor=actor,
        action="TICKET_DELIVERED" if res.fulfillment == Reservation.Fulfillment.DELIVERY else "TICKET_SERVED",
        target_repr=f"Reservation #{res.pk} ({res.short_code})",
        reason=f"Remise validée pour {res.beneficiary.email}",
    )
    return res
