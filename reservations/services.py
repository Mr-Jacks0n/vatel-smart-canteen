"""Services métier de réservation, modification, annulation et génération de tickets QR."""

import io
import secrets

import segno
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import DietaryProfile
from core.models import Notification
from core.services import notify, notify_with_parents
from menus.models import Dish, MealOption, MealService
from wallet.models import Wallet, WalletTransaction
from wallet.services import (
    debit_consumption,
    get_projected_balance,
    has_active_pass,
    refund_debit,
)

from .models import Reservation, ReservationItem

SHORT_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_short_code(service: MealService) -> str:
    for _ in range(30):
        code = "".join(secrets.choice(SHORT_CODE_ALPHABET) for _ in range(6))
        if not Reservation.objects.filter(service=service, short_code=code).exists():
            return code
    raise ValidationError("Impossible de générer un code court unique pour ce service.")


def generate_qr_svg(validation_url: str) -> str:
    """Génère un QR code SVG côté serveur à partir de l'URL de validation uniquement."""
    qr = segno.make(validation_url, error="m")
    buff = io.BytesIO()
    qr.save(buff, kind="svg", scale=6, border=2, dark="#1D1D1B", light="#FFFFFF", xmldecl=False)
    return buff.getvalue().decode("utf-8")


def detect_allergen_conflicts(user, options) -> list[str]:
    """Retourne la liste des allergènes/intolérances du profil présents dans les options choisies."""
    profile = (
        DietaryProfile.objects.filter(user=user)
        .prefetch_related("allergies", "intolerances")
        .first()
    )
    if not profile:
        return []
    user_allergens = set(profile.allergies.values_list("name", flat=True)) | set(
        profile.intolerances.values_list("name", flat=True)
    )
    if not user_allergens:
        return []
    conflicts = set()
    for opt in options:
        dish_allergens = set(opt.dish.allergens.values_list("name", flat=True))
        conflicts |= user_allergens & dish_allergens
    return sorted(conflicts)


@transaction.atomic
def reserve(
    user,
    service_id: int,
    option_ids: list[int],
    *,
    skip_starter: bool = False,
    skip_dessert: bool = False,
    extra_portions: int = 0,
    fulfillment: str = Reservation.Fulfillment.ON_SITE,
    delivery_location: str = "",
    payment_mode_choice: str = Reservation.PaymentMode.WALLET,
    allergy_acknowledged: bool = False,
    booked_by=None,
) -> Reservation:
    """Réservation atomique d'un repas complet sans débit immédiat."""
    if not user.is_diner:
        raise ValidationError("Seuls les élèves et le personnel peuvent réserver un repas.")

    service = MealService.objects.select_for_update().get(pk=service_id)
    if not service.is_published:
        raise ValidationError("Ce service n'est pas publié.")
    if timezone.now() >= service.reservation_deadline:
        raise ValidationError("L'heure limite de réservation est dépassée pour ce service.")

    if Reservation.objects.filter(beneficiary=user, service=service).exclude(
        status=Reservation.Status.CANCELLED
    ).exists():
        raise ValidationError("Vous avez déjà une décision enregistrée pour ce service.")

    # Verrouillage dans l'ordre fixe : MealOption (par id croissant), puis Wallet
    clean_ids = sorted({int(oid) for oid in option_ids if oid})
    if not clean_ids:
        raise ValidationError("Vous devez choisir au moins un plat principal.")

    locked_options = list(
        MealOption.objects.select_for_update()
        .select_related("dish")
        .prefetch_related("dish__allergens")
        .filter(pk__in=clean_ids)
        .order_by("pk")
    )
    if len(locked_options) != len(clean_ids):
        raise ValidationError("Une des options sélectionnées est introuvable.")

    wallet, _ = Wallet.objects.select_for_update().get_or_create(user=user)

    by_category = {}
    for opt in locked_options:
        if opt.service_id != service.id:
            raise ValidationError("Toutes les options doivent appartenir au service choisi.")
        cat = opt.dish.category
        if cat in by_category:
            raise ValidationError(
                f"Vous ne pouvez choisir qu'un seul élément dans la catégorie {opt.dish.get_category_display()}."
            )
        by_category[cat] = opt

    if Dish.Category.PLAT not in by_category:
        raise ValidationError("Un plat principal est obligatoire pour réserver un repas.")

    # Cohérence Sans entrée / Sans dessert
    if Dish.Category.ENTREE in by_category:
        skip_starter = False
    else:
        skip_starter = True
    if Dish.Category.DESSERT in by_category:
        skip_dessert = False
    else:
        skip_dessert = True

    # Portion supplémentaire
    extra_portions = int(extra_portions or 0)
    max_extra = getattr(settings, "MAX_EXTRA_PORTIONS", 1)
    if extra_portions < 0 or extra_portions > max_extra:
        raise ValidationError(
            f"Vous pouvez ajouter au maximum {max_extra} portion(s) supplémentaire(s)."
        )
    if extra_portions > 0 and not service.extra_portion_price:
        raise ValidationError("La portion supplémentaire n'est pas proposée pour ce service.")

    # Vérification des capacités
    for cat, opt in by_category.items():
        needed = 1 + extra_portions if cat == Dish.Category.PLAT else 1
        if opt.reserved_count + needed > opt.capacity:
            raise ValidationError(
                f"Capacité insuffisante pour « {opt.dish.name} » ({opt.remaining} portion(s) restante(s))."
            )

    # Alerte allergène obligatoire côté serveur
    conflicts = detect_allergen_conflicts(user, locked_options)
    if conflicts and not allergy_acknowledged:
        raise ValidationError(
            f"Alerte allergène ({', '.join(conflicts)}) : vous devez cocher la case de confirmation."
        )

    # Livraison
    if fulfillment not in Reservation.Fulfillment.values:
        raise ValidationError("Mode de remise invalide.")
    delivery_fee_paid = 0
    clean_location = (delivery_location or "").strip()
    if fulfillment == Reservation.Fulfillment.DELIVERY:
        if not getattr(settings, "DELIVERY_ENABLED", True):
            raise ValidationError("La livraison est actuellement désactivée.")
        if not clean_location:
            raise ValidationError("Le lieu de livraison (bâtiment, salle ou bureau) est obligatoire.")
        delivery_fee_paid = int(getattr(settings, "DELIVERY_FEE", 500))
    else:
        clean_location = ""

    # Calcul des montants uniquement depuis la base
    meal_price_paid = service.meal_price
    extra_price_paid = service.extra_portion_price or 0
    supplements_total = extra_portions * extra_price_paid + delivery_fee_paid
    total_price = meal_price_paid + supplements_total

    # Mode et statut de paiement
    if has_active_pass(user, on_date=service.date):
        payment_mode = Reservation.PaymentMode.PASS
        if supplements_total > 0:
            payment_status = Reservation.PaymentStatus.TO_PAY_AT_PICKUP
            amount_due_at_pickup = supplements_total
        else:
            payment_status = Reservation.PaymentStatus.SETTLED
            amount_due_at_pickup = 0
    elif payment_mode_choice == Reservation.PaymentMode.PICKUP:
        if not getattr(settings, "PICKUP_PAYMENT_ENABLED", True):
            raise ValidationError("Le paiement au retrait est actuellement désactivé.")
        max_unpaid = getattr(settings, "MAX_UNPAID_RESERVATIONS", 2)
        unpaid_count = Reservation.objects.filter(
            beneficiary=user,
            status=Reservation.Status.CONFIRMED,
            payment_status=Reservation.PaymentStatus.TO_PAY_AT_PICKUP,
        ).count()
        if unpaid_count >= max_unpaid:
            raise ValidationError(
                f"Limite atteinte : vous avez déjà {unpaid_count} réservation(s) à régler au retrait (max {max_unpaid})."
            )
        payment_mode = Reservation.PaymentMode.PICKUP
        payment_status = Reservation.PaymentStatus.TO_PAY_AT_PICKUP
        amount_due_at_pickup = total_price
    else:
        # Par défaut : WALLET avec débit programmé à la veille (aucun débit immédiat!)
        payment_mode = Reservation.PaymentMode.WALLET
        payment_status = Reservation.PaymentStatus.SCHEDULED
        amount_due_at_pickup = 0

    reservation = Reservation.objects.create(
        beneficiary=user,
        booked_by=booked_by or user,
        service=service,
        status=Reservation.Status.CONFIRMED,
        payment_mode=payment_mode,
        payment_status=payment_status,
        skip_starter=skip_starter,
        skip_dessert=skip_dessert,
        extra_portions=extra_portions,
        meal_price_paid=meal_price_paid,
        extra_price_paid=extra_price_paid if extra_portions > 0 else 0,
        delivery_fee_paid=delivery_fee_paid,
        total_price=total_price,
        amount_due_at_pickup=amount_due_at_pickup,
        fulfillment=fulfillment,
        delivery_location=clean_location,
        allergy_acknowledged=bool(conflicts and allergy_acknowledged),
        ticket_token=secrets.token_urlsafe(16),
        short_code=generate_short_code(service),
    )

    for cat, opt in by_category.items():
        portions = 1 + extra_portions if cat == Dish.Category.PLAT else 1
        ReservationItem.objects.create(
            reservation=reservation,
            option=opt,
            category=cat,
            portions=portions,
        )
        opt.reserved_count += portions
        opt.save(update_fields=["reserved_count"])

    # Alerte préventive si solde prévisionnel insuffisant
    if payment_mode == Reservation.PaymentMode.WALLET:
        projected = get_projected_balance(wallet)
        if projected < 0:
            missing = abs(projected)
            notify_with_parents(
                user,
                Notification.Kind.INSUFFICIENT_BALANCE,
                (
                    f"Solde prévisionnel insuffisant pour vos repas programmés "
                    f"(manque estimé : {missing} FCFA avant la clôture)."
                ),
                link="/portefeuille/",
            )

    notify(
        user,
        Notification.Kind.RESERVATION_CONFIRMED,
        f"Réservation confirmée pour le {service.date:%d/%m/%Y} (code {reservation.short_code}).",
        link="/reservations/",
    )
    return reservation


@transaction.atomic
def decline_day(user, service_id: int) -> Reservation:
    """Enregistre « Je ne mange pas ce jour » sans facturation, ni ligne, ni ticket."""
    if not user.is_diner:
        raise ValidationError("Action réservée aux élèves et au personnel.")
    service = MealService.objects.select_for_update().get(pk=service_id)
    if not service.is_published:
        raise ValidationError("Ce service n'est pas publié.")
    if timezone.now() >= service.reservation_deadline:
        raise ValidationError("L'heure limite est dépassée pour ce service.")

    if Reservation.objects.filter(beneficiary=user, service=service).exclude(
        status=Reservation.Status.CANCELLED
    ).exists():
        raise ValidationError("Vous avez déjà une décision enregistrée pour ce service.")

    return Reservation.objects.create(
        beneficiary=user,
        booked_by=user,
        service=service,
        status=Reservation.Status.DECLINED,
        payment_mode="",
        payment_status=Reservation.PaymentStatus.NONE,
        total_price=0,
        amount_due_at_pickup=0,
        ticket_token=None,
        short_code=None,
    )


@transaction.atomic
def cancel_reservation(user, reservation_id: int, actor=None) -> Reservation:
    """Annulation avant l'heure limite, libération des portions et remboursement uniquement si déjà débité."""
    reservation = (
        Reservation.objects.select_for_update()
        .select_related("service", "beneficiary")
        .get(pk=reservation_id, beneficiary=user)
    )
    if reservation.status == Reservation.Status.CANCELLED:
        raise ValidationError("Cette réservation est déjà annulée.")
    if reservation.status == Reservation.Status.SERVED:
        raise ValidationError("Impossible d'annuler un repas déjà servi.")
    if timezone.now() >= reservation.service.reservation_deadline:
        raise ValidationError("L'heure limite d'annulation est dépassée.")

    # Verrouiller les options dans l'ordre fixe avant le portefeuille
    items = list(reservation.items.select_related("option").order_by("option_id"))
    if items:
        option_ids = [item.option_id for item in items]
        locked_options = {
            o.pk: o
            for o in MealOption.objects.select_for_update().filter(pk__in=option_ids).order_by("pk")
        }
        for item in items:
            opt = locked_options[item.option_id]
            opt.reserved_count = max(0, opt.reserved_count - item.portions)
            opt.save(update_fields=["reserved_count"])

    # Remboursement uniquement si un débit CONSUMPTION a déjà eu lieu (cas hebdomadaire ou « Régler maintenant »)
    debit_tx = WalletTransaction.objects.filter(
        reservation=reservation,
        kind=WalletTransaction.Kind.CONSUMPTION,
    ).first()
    if debit_tx is not None:
        refund_debit(
            debit_tx,
            actor=actor or user,
            reason=f"Annulation repas du {reservation.service.date:%d/%m/%Y}",
        )
        reservation.payment_status = Reservation.PaymentStatus.REFUNDED

    reservation.status = Reservation.Status.CANCELLED
    reservation.amount_due_at_pickup = 0
    reservation.cancelled_at = timezone.now()
    reservation.save(update_fields=["status", "payment_status", "amount_due_at_pickup", "cancelled_at"])

    notify(
        user,
        Notification.Kind.RESERVATION_CANCELLED,
        f"Décision annulée pour le {reservation.service.date:%d/%m/%Y}.",
        link="/reservations/",
    )
    return reservation


@transaction.atomic
def modify_reservation(user, reservation_id: int, **reserve_kwargs) -> Reservation:
    """Annulation et recréation de la réservation dans une seule transaction atomique."""
    old = Reservation.objects.select_related("service").get(
        pk=reservation_id, beneficiary=user
    )
    service_id = old.service_id
    cancel_reservation(user, old.pk, actor=user)
    return reserve(user, service_id=service_id, **reserve_kwargs)


@transaction.atomic
def pay_now_scheduled(user, actor=None) -> list[Reservation]:
    """Règle immédiatement les réservations programmées du titulaire (bouton « Régler maintenant »)."""
    scheduled = list(
        Reservation.objects.select_for_update()
        .select_related("service")
        .filter(
            beneficiary=user,
            status=Reservation.Status.CONFIRMED,
            payment_mode=Reservation.PaymentMode.WALLET,
            payment_status=Reservation.PaymentStatus.SCHEDULED,
        )
        .order_by("service__date", "id")
    )
    if not scheduled:
        raise ValidationError("Aucune réservation programmée à régler.")

    settled = []
    for res in scheduled:
        debit_consumption(
            user=user,
            amount=res.total_price,
            actor=actor or user,
            reservation=res,
            reason=f"Règlement manuel repas du {res.service.date:%d/%m/%Y}",
        )
        res.payment_status = Reservation.PaymentStatus.SETTLED
        res.debited_at = timezone.now()
        res.save(update_fields=["payment_status", "debited_at"])
        settled.append(res)
    return settled


@transaction.atomic
def reserve_multiple_days(user, selections: list[dict]) -> list[Reservation]:
    """Réservation atomique de plusieurs jours en une seule opération."""
    if not selections:
        raise ValidationError("Sélectionnez au moins un jour à réserver.")
    created = []
    for item in selections:
        res = reserve(
            user=user,
            service_id=item["service_id"],
            option_ids=item["option_ids"],
            skip_starter=item.get("skip_starter", False),
            skip_dessert=item.get("skip_dessert", False),
            payment_mode_choice=item.get("payment_mode", Reservation.PaymentMode.WALLET),
            allergy_acknowledged=item.get("allergy_acknowledged", False),
        )
        created.append(res)
    return created


@transaction.atomic
def rate_reservation_dish(user, reservation_id: int, score: int):
    """Notation de 1 à 5 étoiles une seule fois par réservation servie."""
    from .models import DishRating

    try:
        score_int = int(score)
    except (TypeError, ValueError):
        raise ValidationError("La note doit être comprise entre 1 et 5.")
    if score_int < 1 or score_int > 5:
        raise ValidationError("La note doit être comprise entre 1 et 5.")

    res = Reservation.objects.select_for_update().get(
        pk=reservation_id, beneficiary=user
    )
    if res.status != Reservation.Status.SERVED:
        raise ValidationError("Vous ne pouvez noter un repas qu'après l'avoir retiré ou reçu.")
    if DishRating.objects.filter(reservation=res).exists():
        raise ValidationError("Vous avez déjà noté cette réservation.")

    return DishRating.objects.create(reservation=res, score=score_int)
