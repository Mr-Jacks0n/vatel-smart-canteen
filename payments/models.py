from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Payment(models.Model):
    """Opération d'encaissement dématérialisée (recharge ponctuelle, prépaiement annuel ou paiement au retrait)."""

    class Kind(models.TextChoices):
        TOPUP = "TOPUP", "Recharge ponctuelle"
        ANNUAL_PREPAYMENT = "ANNUAL_PREPAYMENT", "Prépaiement annuel"
        PICKUP = "PICKUP", "Paiement au retrait"

    class Method(models.TextChoices):
        WAVE = "WAVE", "Wave"
        ORANGE_MONEY = "ORANGE_MONEY", "Orange Money"
        MTN_MOMO = "MTN_MOMO", "MTN MoMo"
        MOOV_MONEY = "MOOV_MONEY", "Moov Money"
        BANK_CARD = "BANK_CARD", "Carte bancaire"
        BANK_TRANSFER = "BANK_TRANSFER", "Virement bancaire"

    class Status(models.TextChoices):
        PENDING = "PENDING", "En attente"
        CONFIRMED = "CONFIRMED", "Confirmé"
        FAILED = "FAILED", "Échoué"

    MOBILE_MONEY_METHODS = (
        Method.WAVE,
        Method.ORANGE_MONEY,
        Method.MTN_MOMO,
        Method.MOOV_MONEY,
    )

    kind = models.CharField("Type d'encaissement", max_length=25, choices=Kind.choices)
    beneficiary = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payments_received",
        verbose_name="Bénéficiaire",
    )
    payer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payments_made",
        verbose_name="Payeur",
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments_confirmed",
        verbose_name="Confirmé par",
    )
    method = models.CharField("Moyen de paiement", max_length=20, choices=Method.choices)
    phone_number = models.CharField(
        "Numéro Mobile Money (fictif)", max_length=30, blank=True
    )
    amount = models.PositiveIntegerField("Montant (FCFA)")
    reference = models.CharField("Référence", max_length=40, unique=True)
    status = models.CharField(
        "Statut", max_length=15, choices=Status.choices, default=Status.PENDING
    )
    reservation = models.ForeignKey(
        "reservations.Reservation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pickup_payments",
        verbose_name="Réservation (paiement au retrait)",
    )
    created_at = models.DateTimeField("Créé le", auto_now_add=True)
    confirmed_at = models.DateTimeField("Confirmé le", null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Paiement"
        verbose_name_plural = "Paiements"
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="payments_amount_gt_0",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(method="BANK_TRANSFER") | Q(kind="ANNUAL_PREPAYMENT")
                ),
                name="payments_bank_transfer_only_for_annual_prepayment",
            ),
            models.UniqueConstraint(
                fields=["reservation"],
                condition=Q(kind="PICKUP", status="CONFIRMED", reservation__isnull=False),
                name="payments_unique_confirmed_pickup_per_reservation",
            ),
        ]

    def clean(self):
        super().clean()
        if self.method == self.Method.BANK_TRANSFER and self.kind != self.Kind.ANNUAL_PREPAYMENT:
            raise ValidationError(
                {"method": "Le virement bancaire est réservé au prépaiement annuel."}
            )

    @property
    def is_mobile_money(self):
        return self.method in self.MOBILE_MONEY_METHODS

    def __str__(self):
        return f"{self.reference} — {self.get_kind_display()} ({self.amount} FCFA)"
