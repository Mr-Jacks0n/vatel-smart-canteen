"""Services de calcul des indicateurs opérationnels et financiers."""

from datetime import timedelta

from django.db.models import Count, F, Sum
from django.utils import timezone

from accounts.models import Department, User
from menus.models import MealService
from payments.models import Payment
from reservations.models import Reservation, ReservationItem
from wallet.models import AnnualPass, Wallet, WalletTransaction


def get_period_bounds(period: str):
    today = timezone.localdate()
    if period == "day":
        return today, today
    if period == "month":
        return today.replace(day=1), today
    # défaut : week
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=6)


def get_financial_report(period: str = "week") -> dict:
    """Calcule les indicateurs financiers sur la période demandée."""
    start_date, end_date = get_period_bounds(period)

    confirmed_payments = Payment.objects.filter(
        status=Payment.Status.CONFIRMED,
        confirmed_at__date__range=(start_date, end_date),
    )

    topup_total = int(
        confirmed_payments.filter(kind=Payment.Kind.TOPUP).aggregate(s=Sum("amount"))["s"] or 0
    )
    annual_total = int(
        confirmed_payments.filter(kind=Payment.Kind.ANNUAL_PREPAYMENT).aggregate(s=Sum("amount"))["s"] or 0
    )
    pickup_total = int(
        confirmed_payments.filter(kind=Payment.Kind.PICKUP).aggregate(s=Sum("amount"))["s"] or 0
    )
    total_collected = topup_total + annual_total + pickup_total

    by_method = list(
        confirmed_payments.values("kind", "method")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("kind", "method")
    )

    active_passes_count = AnnualPass.objects.filter(status=AnnualPass.Status.ACTIVE).count()

    period_reservations = Reservation.objects.filter(
        service__date__range=(start_date, end_date),
        status__in=[Reservation.Status.CONFIRMED, Reservation.Status.SERVED],
    )
    extra_agg = period_reservations.filter(extra_portions__gt=0).aggregate(
        count=Sum("extra_portions"),
        amount=Sum(F("extra_portions") * F("extra_price_paid")),
    )
    delivery_agg = period_reservations.filter(
        fulfillment=Reservation.Fulfillment.DELIVERY
    ).aggregate(
        count=Count("id"),
        amount=Sum("delivery_fee_paid"),
    )

    tx_period = WalletTransaction.objects.filter(
        created_at__date__range=(start_date, end_date)
    )
    consumption_sum = int(
        tx_period.filter(kind=WalletTransaction.Kind.CONSUMPTION).aggregate(s=Sum("amount"))["s"] or 0
    )
    refund_sum = int(
        tx_period.filter(kind=WalletTransaction.Kind.REFUND).aggregate(s=Sum("amount"))["s"] or 0
    )
    net_wallet_consumption = consumption_sum - refund_sum

    scheduled_agg = Reservation.objects.filter(
        status=Reservation.Status.CONFIRMED,
        payment_status=Reservation.PaymentStatus.SCHEDULED,
    ).aggregate(count=Count("id"), amount=Sum("total_price"))

    unpaid_pickup_agg = Reservation.objects.filter(
        status=Reservation.Status.CONFIRMED,
        payment_status=Reservation.PaymentStatus.TO_PAY_AT_PICKUP,
    ).aggregate(count=Count("id"), amount=Sum("amount_due_at_pickup"))

    failed_debit_count = Reservation.objects.filter(
        service__date__range=(start_date, end_date),
        payment_mode=Reservation.PaymentMode.WALLET,
        payment_status=Reservation.PaymentStatus.TO_PAY_AT_PICKUP,
    ).count()

    pass_meals_count = period_reservations.filter(
        payment_mode=Reservation.PaymentMode.PASS
    ).count()

    # Solde total des portefeuilles : argent disponible pour les familles, non compté en recette
    total_wallet_balances = int(Wallet.objects.aggregate(s=Sum("balance"))["s"] or 0)

    pending_payments_agg = Payment.objects.filter(
        status=Payment.Status.PENDING
    ).aggregate(count=Count("id"), amount=Sum("amount"))
    failed_payments_agg = Payment.objects.filter(
        status=Payment.Status.FAILED,
        created_at__date__range=(start_date, end_date),
    ).aggregate(count=Count("id"), amount=Sum("amount"))
    pending_transfers_count = Payment.objects.filter(
        status=Payment.Status.PENDING,
        method=Payment.Method.BANK_TRANSFER,
    ).count()

    return {
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "topup_total": topup_total,
        "annual_total": annual_total,
        "pickup_total": pickup_total,
        "total_collected": total_collected,
        "active_passes_count": active_passes_count,
        "by_method": by_method,
        "extra_portions_count": int(extra_agg["count"] or 0),
        "extra_portions_amount": int(extra_agg["amount"] or 0),
        "delivery_count": int(delivery_agg["count"] or 0),
        "delivery_amount": int(delivery_agg["amount"] or 0),
        "net_wallet_consumption": net_wallet_consumption,
        "scheduled_count": int(scheduled_agg["count"] or 0),
        "scheduled_amount": int(scheduled_agg["amount"] or 0),
        "failed_debit_count": failed_debit_count,
        "pass_meals_count": pass_meals_count,
        "total_wallet_balances": total_wallet_balances,
        "pending_payments_count": int(pending_payments_agg["count"] or 0),
        "pending_payments_amount": int(pending_payments_agg["amount"] or 0),
        "pending_transfers_count": pending_transfers_count,
        "failed_payments_count": int(failed_payments_agg["count"] or 0),
        "failed_payments_amount": int(failed_payments_agg["amount"] or 0),
        "unpaid_pickup_count": int(unpaid_pickup_agg["count"] or 0),
        "unpaid_pickup_amount": int(unpaid_pickup_agg["amount"] or 0),
    }


def get_operational_stats() -> dict:
    today = timezone.localdate()
    users_by_role = dict(
        User.objects.values("role").annotate(c=Count("id")).values_list("role", "c")
    )

    today_active = Reservation.objects.filter(
        service__date=today,
        status__in=[Reservation.Status.CONFIRMED, Reservation.Status.SERVED],
    )
    today_served = today_active.filter(status=Reservation.Status.SERVED).count()
    today_planned = today_active.count()
    today_declined = Reservation.objects.filter(
        service__date=today, status=Reservation.Status.DECLINED
    ).count()
    today_extra = int(today_active.aggregate(s=Sum("extra_portions"))["s"] or 0)

    total_diners = User.objects.filter(
        role__in=[User.Role.ELEVE, User.Role.PERSONNEL], is_active=True
    ).count()
    today_no_response = max(0, total_diners - (today_planned + today_declined))

    # Taux de retrait sur les services passés (<= today)
    past_non_cancelled = Reservation.objects.filter(
        service__date__lte=today,
        status__in=[Reservation.Status.CONFIRMED, Reservation.Status.SERVED],
    )
    past_total = past_non_cancelled.count()
    past_served = past_non_cancelled.filter(status=Reservation.Status.SERVED).count()
    pickup_rate = round((past_served / past_total) * 100, 1) if past_total else 0.0
    not_picked_up = past_total - past_served

    # Statistiques par département pour le personnel
    dept_stats = list(
        Department.objects.annotate(
            staff_count=Count("members", distinct=True),
            reservation_count=Count(
                "members__reservations_as_beneficiary",
                filter=Reservation.objects.filter(
                    status__in=[Reservation.Status.CONFIRMED, Reservation.Status.SERVED]
                ).query.where
                if False
                else None,
            ),
        ).values("id", "name", "staff_count")
    )
    # Calcul exact des réservations actives par département
    res_by_dept = dict(
        Reservation.objects.filter(
            beneficiary__role=User.Role.PERSONNEL,
            status__in=[Reservation.Status.CONFIRMED, Reservation.Status.SERVED],
        )
        .values("beneficiary__department_id")
        .annotate(c=Count("id"))
        .values_list("beneficiary__department_id", "c")
    )
    for row in dept_stats:
        row["reservations_count"] = res_by_dept.get(row["id"], 0)

    # Plats les plus demandés
    top_dishes = list(
        ReservationItem.objects.filter(
            reservation__status__in=[
                Reservation.Status.CONFIRMED,
                Reservation.Status.SERVED,
            ]
        )
        .values("option__dish__name", "category")
        .annotate(portions=Sum("portions"))
        .order_by("-portions")[:5]
    )

    # Données graphique semaine (Chart.js via json_script)
    monday = today - timedelta(days=today.weekday())
    week_days = [monday + timedelta(days=i) for i in range(5)]
    chart_labels = [d.strftime("%a %d/%m") for d in week_days]
    chart_values = [
        Reservation.objects.filter(
            service__date=d,
            status__in=[Reservation.Status.CONFIRMED, Reservation.Status.SERVED],
        ).count()
        for d in week_days
    ]

    return {
        "users_by_role": users_by_role,
        "today_planned": today_planned,
        "today_served": today_served,
        "today_remaining": max(0, today_planned - today_served),
        "today_declined": today_declined,
        "today_no_response": today_no_response,
        "today_extra": today_extra,
        "pickup_rate": pickup_rate,
        "not_picked_up": not_picked_up,
        "dept_stats": dept_stats,
        "top_dishes": top_dishes,
        "chart_data": {"labels": chart_labels, "values": chart_values},
    }
