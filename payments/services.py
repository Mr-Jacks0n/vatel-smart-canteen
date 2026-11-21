"""Services de paiement : 3 opérations distinctes, montants validés par le serveur et idempotence."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import ParentLink, User
from core.models import Notification
from core.services import log_sensitive_action, notify, notify_with_parents
from wallet.models import AnnualPass, Wallet
from wallet.services import (
    activate_annual_pass,
    credit_topup,
    get_school_year_bounds,
    has_active_pass,
)

from .models import Payment
from .providers import get_provider


def _assert_parent_linked(parent, student):
    if parent.role != User.Role.PARENT:
        raise ValidationError("Cette opération est réservée aux parents.")
    if not ParentLink.objects.filter(parent=parent, child=student).exists():
        raise ValidationError("Vous n'êtes pas autorisé à agir pour cet élève.")


@transaction.atomic
def create_payment(
    *,
    kind: str,
    beneficiary: User,
    payer: User,
    method: str,
    amount=None,
    phone_number: str = "",
    reservation=None,
) -> Payment:
    """Crée un paiement PENDING avec validation stricte côté serveur."""
    if kind not in Payment.Kind.values:
        raise ValidationError("Type de paiement invalide.")
    if method not in Payment.Method.values:
        raise ValidationError(
            "Moyen de paiement non autorisé. Aucun paiement physique n'est accepté."
        )
    if method == Payment.Method.BANK_TRANSFER and kind != Payment.Kind.ANNUAL_PREPAYMENT:
        raise ValidationError("Le virement bancaire est réservé au prépaiement annuel.")

    provider = get_provider(method)

    if kind == Payment.Kind.TOPUP:
        if not beneficiary.is_diner:
            raise ValidationError("Seul un élève ou un membre du personnel peut être rechargé.")
        if payer != beneficiary:
            _assert_parent_linked(payer, beneficiary)
        if has_active_pass(beneficiary):
            raise ValidationError(
                "La recharge ponctuelle n'est pas proposée pendant la validité d'un forfait « Année soldée »."
            )
        allowed_amounts = getattr(settings, "TOPUP_AMOUNTS", [1000, 2000, 5000, 10000, 20000])
        try:
            server_amount = int(amount)
        except (TypeError, ValueError):
            raise ValidationError("Montant de recharge invalide.")
        if server_amount not in allowed_amounts:
            raise ValidationError(
                f"Montant non autorisé. Valeurs acceptées : {', '.join(str(a) for a in allowed_amounts)} FCFA."
            )
        wallet, _ = Wallet.objects.get_or_create(user=beneficiary)
        max_balance = getattr(settings, "WALLET_MAX_BALANCE", 100000)
        if wallet.balance + server_amount > max_balance:
            raise ValidationError(
                f"Cette recharge dépasserait le plafond de solde de {max_balance} FCFA."
            )

    elif kind == Payment.Kind.ANNUAL_PREPAYMENT:
        _assert_parent_linked(payer, beneficiary)
        if beneficiary.role != User.Role.ELEVE:
            raise ValidationError("Le prépaiement annuel est réservé aux élèves.")
        school_year, _, _ = get_school_year_bounds()
        if AnnualPass.objects.filter(
            student=beneficiary,
            school_year=school_year,
            status=AnnualPass.Status.ACTIVE,
        ).exists():
            raise ValidationError(
                f"Un forfait « Année soldée » est déjà actif pour {beneficiary.full_name}."
            )
        server_amount = int(getattr(settings, "ANNUAL_PASS_PRICE", 180000))

    elif kind == Payment.Kind.PICKUP:
        if reservation is None:
            raise ValidationError("Une réservation est requise pour un paiement au retrait.")
        if reservation.beneficiary_id != beneficiary.id or payer.id != reservation.beneficiary_id:
            raise ValidationError(
                "Un paiement au retrait ne peut viser que votre propre réservation."
            )
        if reservation.amount_due_at_pickup <= 0:
            raise ValidationError("Aucun montant n'est dû pour cette réservation.")
        server_amount = int(reservation.amount_due_at_pickup)

    reference = provider.generate_reference(kind)
    payment_kwargs = {
        "kind": kind,
        "beneficiary": beneficiary,
        "payer": payer,
        "method": method,
        "phone_number": (phone_number or "").strip()[:30] if method in Payment.MOBILE_MONEY_METHODS else "",
        "amount": server_amount,
        "reference": reference,
        "status": Payment.Status.PENDING,
    }
    if reservation is not None and hasattr(Payment, "reservation"):
        payment_kwargs["reservation"] = reservation

    payment = Payment.objects.create(**payment_kwargs)
    return payment


@transaction.atomic
def confirm_payment(reference: str, actor=None) -> Payment:
    """Confirme un paiement côté serveur de manière atomique et idempotente."""
    # Verrouiller le portefeuille (si présent) puis le paiement dans un ordre fixe
    payment_preview = Payment.objects.select_related("beneficiary", "payer").get(reference=reference)
    if payment_preview.beneficiary.is_diner:
        Wallet.objects.select_for_update().filter(user=payment_preview.beneficiary).first()

    payment = Payment.objects.select_for_update().select_related(
        "beneficiary", "payer"
    ).get(reference=reference)

    if payment.status == Payment.Status.CONFIRMED:
        return payment
    if payment.status == Payment.Status.FAILED:
        raise ValidationError("Impossible de confirmer un paiement déjà échoué.")

    if payment.method == Payment.Method.BANK_TRANSFER:
        if not actor or actor.role != User.Role.ADMIN:
            raise ValidationError(
                "Seul un administrateur peut confirmer un virement bancaire."
            )
        payment.confirmed_by = actor

    if payment.kind == Payment.Kind.TOPUP:
        credit_topup(payment, actor=actor or payment.payer)
        notify_with_parents(
            payment.beneficiary,
            Notification.Kind.PAYMENT_CONFIRMED,
            f"Recharge de {payment.amount} FCFA confirmée ({payment.get_method_display()}, réf. {payment.reference}).",
            link="/portefeuille/",
        )

    elif payment.kind == Payment.Kind.ANNUAL_PREPAYMENT:
        activate_annual_pass(
            student=payment.beneficiary,
            actor=actor or payment.payer,
            payment=payment,
        )
        notify(
            payment.payer,
            Notification.Kind.PAYMENT_CONFIRMED,
            f"Prépaiement annuel confirmé pour {payment.beneficiary.full_name} ({payment.amount} FCFA). Forfait « Année soldée » activé.",
            link="/parents/",
        )
        notify(
            payment.beneficiary,
            Notification.Kind.PAYMENT_CONFIRMED,
            "Votre forfait « Année soldée » est désormais actif.",
            link="/portefeuille/",
        )
        if payment.method == Payment.Method.BANK_TRANSFER and actor:
            log_sensitive_action(
                actor=actor,
                action="BANK_TRANSFER_CONFIRMED",
                target_repr=f"Payment {payment.reference} ({payment.amount} FCFA)",
                reason=f"Confirmation virement prépaiement annuel pour {payment.beneficiary.email}",
            )

    elif payment.kind == Payment.Kind.PICKUP:
        if hasattr(payment, "reservation") and payment.reservation_id:
            reservation = payment.reservation
            reservation.amount_due_at_pickup = 0
            reservation.payment_status = "SETTLED"
            reservation.save(update_fields=["amount_due_at_pickup", "payment_status"])
            notify(
                payment.beneficiary,
                Notification.Kind.PAYMENT_CONFIRMED,
                f"Paiement au retrait de {payment.amount} FCFA confirmé ({payment.get_method_display()}).",
                link="/reservations/",
            )

    payment.status = Payment.Status.CONFIRMED
    payment.confirmed_at = timezone.now()
    payment.save(update_fields=["status", "confirmed_at", "confirmed_by"])
    return payment


@transaction.atomic
def fail_payment(reference: str, actor=None) -> Payment:
    payment = Payment.objects.select_for_update().select_related(
        "beneficiary", "payer"
    ).get(reference=reference)

    if payment.status == Payment.Status.FAILED:
        return payment
    if payment.status == Payment.Status.CONFIRMED:
        raise ValidationError("Impossible d'échouer un paiement déjà confirmé.")

    payment.status = Payment.Status.FAILED
    payment.save(update_fields=["status"])
    notify(
        payment.payer,
        Notification.Kind.PAYMENT_FAILED,
        f"Le paiement {payment.get_kind_display()} de {payment.amount} FCFA ({payment.reference}) a échoué.",
    )
    return payment
