from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from accounts.models import User


class Wallet(models.Model):
    class DebitFrequency(models.TextChoices):
        DAILY = "DAILY", "Journalière (la veille de chaque repas)"
        WEEKLY = "WEEKLY", "Hebdomadaire (la veille de la semaine)"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wallet",
        verbose_name="Titulaire",
    )
    balance = models.PositiveIntegerField("Solde Vatel Cantine (FCFA)", default=0)
    debit_frequency = models.CharField(
        "Fréquence de débit",
        max_length=10,
        choices=DebitFrequency.choices,
        default=DebitFrequency.DAILY,
    )
    auto_debit_enabled = models.BooleanField("Débit automatique activé", default=True)
    low_balance_notified = models.BooleanField("Alerte solde faible envoyée", default=False)
    updated_at = models.DateTimeField("Mis à jour le", auto_now=True)

    class Meta:
        verbose_name = "Portefeuille"
        verbose_name_plural = "Portefeuilles"
        constraints = [
            models.CheckConstraint(
                condition=Q(balance__gte=0),
                name="wallet_balance_gte_0",
            ),
        ]

    def __str__(self):
        return f"Portefeuille de {self.user.full_name} ({self.balance} FCFA)"


class WalletTransaction(models.Model):
    class Kind(models.TextChoices):
        TOPUP_CREDIT = "TOPUP_CREDIT", "Recharge"
        CONSUMPTION = "CONSUMPTION", "Repas réservé"
        REFUND = "REFUND", "Remboursement"
        ADMIN_ADJUSTMENT = "ADMIN_ADJUSTMENT", "Ajustement administratif"

    class Direction(models.TextChoices):
        CREDIT = "+", "Crédit (+)"
        DEBIT = "-", "Débit (−)"

    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        related_name="transactions",
        verbose_name="Portefeuille",
    )
    kind = models.CharField("Type", max_length=20, choices=Kind.choices)
    direction = models.CharField(
        "Sens", max_length=1, choices=Direction.choices, default=Direction.CREDIT
    )
    amount = models.PositiveIntegerField("Montant (FCFA)")
    balance_after = models.PositiveIntegerField("Solde après opération (FCFA)")
    payment = models.OneToOneField(
        "payments.Payment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="wallet_credit",
        verbose_name="Paiement d'origine",
    )
    reservation = models.ForeignKey(
        "reservations.Reservation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="wallet_transactions",
        verbose_name="Réservation",
    )
    refund_of = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="refund_transaction",
        verbose_name="Remboursement du débit",
    )
    reason = models.CharField("Motif", max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_wallet_transactions",
        verbose_name="Auteur",
    )
    created_at = models.DateTimeField("Date", auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Mouvement de portefeuille"
        verbose_name_plural = "Mouvements de portefeuille"
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="wallet_tx_amount_gt_0",
            ),
            models.UniqueConstraint(
                fields=["reservation"],
                condition=Q(kind="CONSUMPTION", reservation__isnull=False),
                name="wallet_unique_consumption_per_reservation",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.direction}{self.amount} FCFA"


class AnnualPass(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Actif"
        CANCELLED = "CANCELLED", "Annulé"

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="annual_passes",
        limit_choices_to={"role": User.Role.ELEVE},
        verbose_name="Élève",
    )
    school_year = models.CharField("Année scolaire", max_length=20)
    valid_from = models.DateField("Valide du")
    valid_until = models.DateField("Valide jusqu'au")
    payment = models.OneToOneField(
        "payments.Payment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="annual_pass",
        verbose_name="Paiement d'origine",
    )
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activated_annual_passes",
        verbose_name="Activé par",
    )
    reason = models.CharField("Motif (activation manuelle)", max_length=255, blank=True)
    status = models.CharField(
        "Statut", max_length=15, choices=Status.choices, default=Status.ACTIVE
    )
    created_at = models.DateTimeField("Créé le", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Forfait « Année soldée »"
        verbose_name_plural = "Forfaits « Année soldée »"
        constraints = [
            models.UniqueConstraint(
                fields=["student", "school_year"],
                condition=Q(status="ACTIVE"),
                name="wallet_unique_active_pass_per_student_year",
            ),
        ]

    def clean(self):
        super().clean()
        if self.student_id and self.student.role != User.Role.ELEVE:
            raise ValidationError(
                {"student": "Le forfait « Année soldée » est réservé aux élèves."}
            )
        if not self.payment_id and not self.reason:
            raise ValidationError(
                {"reason": "Un motif est obligatoire pour une activation manuelle."}
            )

    def __str__(self):
        return f"Année soldée {self.school_year} — {self.student.full_name}"
