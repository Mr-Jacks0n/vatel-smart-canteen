"""Processus de clôture quotidienne idempotent des réservations."""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.models import Notification
from core.services import notify_with_parents
from menus.models import MealOption, MealService
from reservations.models import Reservation
from wallet.models import Wallet, WalletTransaction
from wallet.services import debit_consumption


def _get_week_bounds(d):
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


@transaction.atomic
def _apply_insufficient_balance(res: Reservation, missing_amount: int):
    pickup_enabled = getattr(settings, "PICKUP_PAYMENT_ENABLED", True)
    if pickup_enabled:
        res.payment_status = Reservation.PaymentStatus.TO_PAY_AT_PICKUP
        res.amount_due_at_pickup = res.total_price
        res.save(update_fields=["payment_status", "amount_due_at_pickup"])
        action_msg = "basculé en « À régler au retrait »"
        outcome = "fallback_pickup"
    else:
        items = list(res.items.select_related("option").order_by("option_id"))
        if items:
            option_ids = [i.option_id for i in items]
            locked_opts = {
                o.pk: o
                for o in MealOption.objects.select_for_update()
                .filter(pk__in=option_ids)
                .order_by("pk")
            }
            for item in items:
                opt = locked_opts[item.option_id]
                opt.reserved_count = max(0, opt.reserved_count - item.portions)
                opt.save(update_fields=["reserved_count"])
        res.status = Reservation.Status.CANCELLED
        res.payment_status = Reservation.PaymentStatus.NONE
        res.amount_due_at_pickup = 0
        res.cancelled_at = timezone.now()
        res.save(
            update_fields=["status", "payment_status", "amount_due_at_pickup", "cancelled_at"]
        )
        action_msg = "annulé (mode paiement au retrait désactivé)"
        outcome = "cancelled"

    notify_with_parents(
        res.beneficiary,
        Notification.Kind.INSUFFICIENT_BALANCE,
        (
            f"Solde insuffisant à la clôture pour le repas du {res.service.date:%d/%m/%Y} "
            f"(manque {missing_amount} FCFA) : repas {action_msg}."
        ),
        link="/portefeuille/",
    )
    return outcome


@transaction.atomic
def run_closure(target_date=None, force: bool = False) -> dict:
    """
    Exécute la clôture quotidienne de manière idempotente.
    - target_date : date de service ciblée (si fournie) ; sinon tous les services publiés dont l'heure limite est atteinte.
    - force=True : permet d'exécuter la clôture avant l'heure limite (démonstration admin).
    """
    now = timezone.now()
    services_qs = MealService.objects.select_for_update().filter(is_published=True)
    if target_date is not None:
        services_qs = services_qs.filter(date=target_date)
    elif not force:
        services_qs = services_qs.filter(reservation_deadline__lte=now)

    services = list(services_qs.order_by("date"))
    summary = {
        "services_closed": len(services),
        "debited_count": 0,
        "debited_amount": 0,
        "fallback_pickup_count": 0,
        "cancelled_count": 0,
        "executed_at": now,
    }
    if not services:
        return summary

    service_ids = [s.id for s in services]

    # Identifier les semaines dont on clôture le premier jour de service (pour fréquence WEEKLY)
    weekly_service_ids = set(service_ids)
    for svc in services:
        monday, sunday = _get_week_bounds(svc.date)
        first_svc_of_week = (
            MealService.objects.filter(
                is_published=True, date__range=(monday, sunday)
            )
            .order_by("date")
            .first()
        )
        if first_svc_of_week and first_svc_of_week.id == svc.id:
            week_ids = MealService.objects.filter(
                is_published=True, date__range=(monday, sunday)
            ).values_list("id", flat=True)
            weekly_service_ids.update(week_ids)

    # Récupérer toutes les réservations SCHEDULED éligibles (DAILY sur service_ids, WEEKLY sur weekly_service_ids)
    candidates = list(
        Reservation.objects.select_for_update()
        .select_related("beneficiary", "service")
        .filter(
            status=Reservation.Status.CONFIRMED,
            payment_mode=Reservation.PaymentMode.WALLET,
            payment_status=Reservation.PaymentStatus.SCHEDULED,
            service_id__in=weekly_service_ids,
        )
        .order_by("beneficiary_id", "service__date", "id")
    )

    by_user = {}
    for res in candidates:
        by_user.setdefault(res.beneficiary_id, []).append(res)

    for user_id, user_reservations in by_user.items():
        wallet, _ = Wallet.objects.select_for_update().get_or_create(user_id=user_id)
        for res in user_reservations:
            # Si utilisateur en DAILY, ne traiter que les services réellement clôturés
            if (
                wallet.debit_frequency == Wallet.DebitFrequency.DAILY
                and res.service_id not in service_ids
            ):
                continue

            # Idempotence : si déjà débité en base, s'assurer que le statut est SETTLED
            if WalletTransaction.objects.filter(
                reservation=res, kind=WalletTransaction.Kind.CONSUMPTION
            ).exists():
                if res.payment_status != Reservation.PaymentStatus.SETTLED:
                    res.payment_status = Reservation.PaymentStatus.SETTLED
                    res.debited_at = res.debited_at or now
                    res.save(update_fields=["payment_status", "debited_at"])
                continue

            wallet.refresh_from_db()
            if wallet.auto_debit_enabled and wallet.balance >= res.total_price:
                debit_consumption(
                    user=res.beneficiary,
                    amount=res.total_price,
                    actor=None,
                    reservation=res,
                    reason=f"Clôture repas du {res.service.date:%d/%m/%Y}",
                )
                res.payment_status = Reservation.PaymentStatus.SETTLED
                res.debited_at = now
                res.save(update_fields=["payment_status", "debited_at"])
                summary["debited_count"] += 1
                summary["debited_amount"] += res.total_price
            else:
                missing = max(0, res.total_price - wallet.balance) if wallet.auto_debit_enabled else res.total_price
                outcome = _apply_insufficient_balance(res, missing)
                if outcome == "fallback_pickup":
                    summary["fallback_pickup_count"] += 1
                else:
                    summary["cancelled_count"] += 1

    for svc in services:
        if not svc.closed_at:
            svc.closed_at = now
            svc.save(update_fields=["closed_at"])

    return summary


def trigger_pending_closures_if_needed():
    """Déclenchement automatique au premier accès équipe ou administration après l'heure limite."""
    now = timezone.now()
    if MealService.objects.filter(
        is_published=True,
        reservation_deadline__lte=now,
        closed_at__isnull=True,
    ).exists():
        return run_closure()
    return None
