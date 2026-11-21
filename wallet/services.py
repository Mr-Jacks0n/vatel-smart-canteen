"""Services métier du portefeuille et du forfait « Année soldée »."""

from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.models import User
from core.models import Notification
from core.services import log_sensitive_action, notify_with_parents

from .models import AnnualPass, Wallet, WalletTransaction


def get_school_year_bounds():
    label = getattr(settings, "SCHOOL_YEAR_LABEL", "2026-2027")
    start = date.fromisoformat(getattr(settings, "SCHOOL_YEAR_START", "2026-09-01"))
    end = date.fromisoformat(getattr(settings, "SCHOOL_YEAR_END", "2027-06-30"))
    return label, start, end


def get_active_pass(user, on_date=None):
    if not user or user.role != User.Role.ELEVE:
        return None
    target_date = on_date or timezone.localdate()
    return (
        AnnualPass.objects.filter(
            student=user,
            status=AnnualPass.Status.ACTIVE,
            valid_from__lte=target_date,
            valid_until__gte=target_date,
        )
        .select_related("payment")
        .first()
    )


def has_active_pass(user, on_date=None) -> bool:
    return get_active_pass(user, on_date=on_date) is not None


def get_scheduled_debit_total(user) -> int:
    """Somme des réservations en attente de débit à la veille (SCHEDULED)."""
    if not hasattr(user, "reservations_as_beneficiary"):
        return 0
    agg = user.reservations_as_beneficiary.filter(
        status="CONFIRMED",
        payment_mode="WALLET",
        payment_status="SCHEDULED",
    ).aggregate(total=Sum("total_price"))
    return int(agg["total"] or 0)


def get_projected_balance(wallet: Wallet) -> int:
    return wallet.balance - get_scheduled_debit_total(wallet.user)


def check_and_notify_low_balance(wallet: Wallet):
    """Envoie une seule notification par franchissement du seuil de solde faible, jamais sous forfait."""
    if has_active_pass(wallet.user):
        return
    threshold = getattr(settings, "LOW_BALANCE_THRESHOLD", 2000)
    if wallet.balance < threshold:
        if not wallet.low_balance_notified:
            wallet.low_balance_notified = True
            wallet.save(update_fields=["low_balance_notified", "updated_at"])
            notify_with_parents(
                wallet.user,
                Notification.Kind.LOW_BALANCE,
                (
                    f"Solde Vatel Cantine faible ({wallet.balance} FCFA, "
                    f"seuil : {threshold} FCFA). Pensez à recharger."
                ),
                link="/portefeuille/",
            )
    elif wallet.low_balance_notified:
        wallet.low_balance_notified = False
        wallet.save(update_fields=["low_balance_notified", "updated_at"])


@transaction.atomic
def credit_topup(payment, actor=None):
    """Crédite le portefeuille suite à un paiement TOPUP confirmé (atomique et idempotent)."""
    existing = WalletTransaction.objects.filter(payment=payment).first()
    if existing:
        return existing

    wallet, _ = Wallet.objects.select_for_update().get_or_create(user=payment.beneficiary)
    max_balance = getattr(settings, "WALLET_MAX_BALANCE", 100000)
    if wallet.balance + payment.amount > max_balance:
        raise ValidationError(
            f"Plafond de solde ({max_balance} FCFA) dépassé."
        )

    wallet.balance += payment.amount
    wallet.save(update_fields=["balance", "updated_at"])

    tx = WalletTransaction.objects.create(
        wallet=wallet,
        kind=WalletTransaction.Kind.TOPUP_CREDIT,
        direction=WalletTransaction.Direction.CREDIT,
        amount=payment.amount,
        balance_after=wallet.balance,
        payment=payment,
        reason=f"Recharge {payment.get_method_display()} ({payment.reference})",
        created_by=actor or payment.payer,
    )
    check_and_notify_low_balance(wallet)
    return tx


@transaction.atomic
def debit_consumption(user, amount: int, actor=None, reservation=None, reason=""):
    """Débit CONSUMPTION (exécuté uniquement par la clôture ou « Régler maintenant »)."""
    if amount <= 0:
        raise ValidationError("Le montant du débit doit être strictement positif.")

    wallet = Wallet.objects.select_for_update().get(user=user)
    if reservation is not None and hasattr(WalletTransaction, "reservation"):
        existing = WalletTransaction.objects.filter(
            kind=WalletTransaction.Kind.CONSUMPTION,
            reservation=reservation,
        ).first()
        if existing:
            return existing

    if wallet.balance < amount:
        raise ValidationError("Solde Vatel Cantine insuffisant.")

    wallet.balance -= amount
    wallet.save(update_fields=["balance", "updated_at"])

    tx_kwargs = {
        "wallet": wallet,
        "kind": WalletTransaction.Kind.CONSUMPTION,
        "direction": WalletTransaction.Direction.DEBIT,
        "amount": amount,
        "balance_after": wallet.balance,
        "reason": reason or "Débit repas réservé",
        "created_by": actor or user,
    }
    if reservation is not None and hasattr(WalletTransaction, "reservation"):
        tx_kwargs["reservation"] = reservation

    tx = WalletTransaction.objects.create(**tx_kwargs)
    check_and_notify_low_balance(wallet)
    return tx


@transaction.atomic
def refund_debit(debit_tx: WalletTransaction, actor=None, reason=""):
    """Remboursement unique d'un débit de consommation."""
    if debit_tx.kind != WalletTransaction.Kind.CONSUMPTION:
        raise ValidationError("Seul un débit de consommation peut être remboursé.")

    existing = WalletTransaction.objects.filter(refund_of=debit_tx).first()
    if existing:
        raise ValidationError("Ce débit a déjà été remboursé.")

    wallet = Wallet.objects.select_for_update().get(pk=debit_tx.wallet_id)
    wallet.balance += debit_tx.amount
    wallet.save(update_fields=["balance", "updated_at"])

    tx_kwargs = {
        "wallet": wallet,
        "kind": WalletTransaction.Kind.REFUND,
        "direction": WalletTransaction.Direction.CREDIT,
        "amount": debit_tx.amount,
        "balance_after": wallet.balance,
        "refund_of": debit_tx,
        "reason": reason or "Remboursement annulation avant clôture",
        "created_by": actor or wallet.user,
    }
    if hasattr(WalletTransaction, "reservation") and getattr(debit_tx, "reservation_id", None):
        tx_kwargs["reservation_id"] = debit_tx.reservation_id

    tx = WalletTransaction.objects.create(**tx_kwargs)
    check_and_notify_low_balance(wallet)
    return tx


@transaction.atomic
def admin_adjustment(wallet_user, amount: int, direction: str, reason: str, actor):
    """Ajustement administratif journalisé avec motif obligatoire."""
    if actor.role != User.Role.ADMIN:
        raise ValidationError("Seul un administrateur peut effectuer un ajustement.")
    if amount <= 0:
        raise ValidationError("Le montant doit être strictement positif.")
    if direction not in (
        WalletTransaction.Direction.CREDIT,
        WalletTransaction.Direction.DEBIT,
    ):
        raise ValidationError("Sens d'ajustement invalide.")
    if not reason or not reason.strip():
        raise ValidationError("Un motif est obligatoire pour tout ajustement administratif.")

    wallet = Wallet.objects.select_for_update().get(user=wallet_user)
    if direction == WalletTransaction.Direction.DEBIT:
        if wallet.balance < amount:
            raise ValidationError("Solde insuffisant pour cet ajustement négatif.")
        wallet.balance -= amount
    else:
        wallet.balance += amount
    wallet.save(update_fields=["balance", "updated_at"])

    tx = WalletTransaction.objects.create(
        wallet=wallet,
        kind=WalletTransaction.Kind.ADMIN_ADJUSTMENT,
        direction=direction,
        amount=amount,
        balance_after=wallet.balance,
        reason=reason.strip(),
        created_by=actor,
    )
    log_sensitive_action(
        actor=actor,
        action="ADMIN_ADJUSTMENT",
        target_repr=f"Wallet {wallet.user.email} ({direction}{amount} FCFA)",
        reason=reason.strip(),
    )
    check_and_notify_low_balance(wallet)
    return tx


@transaction.atomic
def activate_annual_pass(student, actor, payment=None, reason=""):
    """Active le forfait « Année soldée » (ne crédite jamais le portefeuille)."""
    if student.role != User.Role.ELEVE:
        raise ValidationError("Le forfait « Année soldée » est réservé aux élèves.")

    if payment is not None:
        existing_from_payment = AnnualPass.objects.filter(payment=payment).first()
        if existing_from_payment:
            return existing_from_payment

    school_year, valid_from, valid_until = get_school_year_bounds()
    if AnnualPass.objects.filter(
        student=student,
        school_year=school_year,
        status=AnnualPass.Status.ACTIVE,
    ).exists():
        raise ValidationError(
            f"Un forfait « Année soldée » est déjà actif pour {student.full_name} ({school_year})."
        )

    if payment is None:
        if actor.role != User.Role.ADMIN:
            raise ValidationError("Seul un administrateur peut activer un forfait manuellement.")
        if not reason or not reason.strip():
            raise ValidationError("Un motif est obligatoire pour l'activation manuelle d'un forfait.")

    annual_pass = AnnualPass.objects.create(
        student=student,
        school_year=school_year,
        valid_from=valid_from,
        valid_until=valid_until,
        payment=payment,
        activated_by=actor,
        reason=reason.strip() if reason else "",
        status=AnnualPass.Status.ACTIVE,
    )
    if payment is None:
        log_sensitive_action(
            actor=actor,
            action="MANUAL_ANNUAL_PASS_ACTIVATION",
            target_repr=f"AnnualPass {student.email} ({school_year})",
            reason=reason.strip(),
        )
    return annual_pass


@transaction.atomic
def update_debit_settings(wallet_user, debit_frequency: str, auto_debit_enabled: bool):
    if debit_frequency not in (
        Wallet.DebitFrequency.DAILY,
        Wallet.DebitFrequency.WEEKLY,
    ):
        raise ValidationError("Fréquence de débit invalide.")
    wallet = Wallet.objects.select_for_update().get(user=wallet_user)
    wallet.debit_frequency = debit_frequency
    wallet.auto_debit_enabled = bool(auto_debit_enabled)
    wallet.save(update_fields=["debit_frequency", "auto_debit_enabled", "updated_at"])
    return wallet
