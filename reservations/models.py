from django.conf import settings
from django.db import models
from django.db.models import Q

from menus.models import Dish, MealOption, MealService


class Reservation(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "CONFIRMED", "Confirmée"
        DECLINED = "DECLINED", "Je ne mange pas ce jour"
        CANCELLED = "CANCELLED", "Annulée"
        SERVED = "SERVED", "Servie"

    class PaymentMode(models.TextChoices):
        PASS = "PASS", "Forfait « Année soldée »"
        WALLET = "WALLET", "Solde Vatel Cantine (débit à la veille)"
        PICKUP = "PICKUP", "Paiement au retrait"

    class PaymentStatus(models.TextChoices):
        NONE = "NONE", "Non facturé"
        SCHEDULED = "SCHEDULED", "Débit programmé (veille)"
        SETTLED = "SETTLED", "Réglé"
        TO_PAY_AT_PICKUP = "TO_PAY_AT_PICKUP", "À régler au retrait"
        REFUNDED = "REFUNDED", "Remboursé"

    class Fulfillment(models.TextChoices):
        ON_SITE = "ON_SITE", "Retrait au comptoir"
        DELIVERY = "DELIVERY", "Livraison"

    beneficiary = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reservations_as_beneficiary",
        verbose_name="Bénéficiaire",
    )
    booked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reservations_booked",
        verbose_name="Réservé par",
    )
    service = models.ForeignKey(
        MealService,
        on_delete=models.PROTECT,
        related_name="reservations",
        verbose_name="Service",
    )
    status = models.CharField(
        "Statut", max_length=15, choices=Status.choices, default=Status.CONFIRMED
    )
    payment_mode = models.CharField(
        "Mode de paiement", max_length=15, choices=PaymentMode.choices, blank=True
    )
    payment_status = models.CharField(
        "Statut de paiement",
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.NONE,
    )
    skip_starter = models.BooleanField("Sans entrée", default=False)
    skip_dessert = models.BooleanField("Sans dessert", default=False)
    extra_portions = models.PositiveIntegerField("Portions supplémentaires", default=0)

    meal_price_paid = models.PositiveIntegerField("Prix repas (FCFA)", default=0)
    extra_price_paid = models.PositiveIntegerField("Prix portion supp. (FCFA)", default=0)
    delivery_fee_paid = models.PositiveIntegerField("Frais de livraison (FCFA)", default=0)
    total_price = models.PositiveIntegerField("Total (FCFA)", default=0)
    amount_due_at_pickup = models.PositiveIntegerField("Reste dû au retrait (FCFA)", default=0)

    fulfillment = models.CharField(
        "Mode de remise",
        max_length=15,
        choices=Fulfillment.choices,
        default=Fulfillment.ON_SITE,
    )
    delivery_location = models.CharField(
        "Lieu de livraison", max_length=200, blank=True
    )

    debited_at = models.DateTimeField("Débité le", null=True, blank=True)
    allergy_acknowledged = models.BooleanField("Alerte allergène confirmée", default=False)

    ticket_token = models.CharField(
        "Jeton ticket", max_length=40, unique=True, null=True, blank=True
    )
    short_code = models.CharField(
        "Code court", max_length=6, null=True, blank=True
    )
    served_at = models.DateTimeField("Servi / livré le", null=True, blank=True)
    served_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="served_reservations",
        verbose_name="Validé par",
    )
    created_at = models.DateTimeField("Créée le", auto_now_add=True)
    cancelled_at = models.DateTimeField("Annulée le", null=True, blank=True)

    class Meta:
        ordering = ["-service__date", "-created_at"]
        verbose_name = "Réservation"
        verbose_name_plural = "Réservations"
        constraints = [
            models.UniqueConstraint(
                fields=["beneficiary", "service"],
                condition=~Q(status="CANCELLED"),
                name="reservations_unique_active_per_beneficiary_service",
            ),
            models.UniqueConstraint(
                fields=["service", "short_code"],
                condition=Q(short_code__isnull=False),
                name="reservations_unique_short_code_per_service",
            ),
        ]

    @property
    def status_display_label(self):
        if self.status == self.Status.SERVED and self.fulfillment == self.Fulfillment.DELIVERY:
            return "Livré"
        return self.get_status_display()

    def __str__(self):
        return f"{self.beneficiary.full_name} — {self.service} ({self.status_display_label})"


class ReservationItem(models.Model):
    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Réservation",
    )
    option = models.ForeignKey(
        MealOption,
        on_delete=models.PROTECT,
        related_name="reservation_items",
        verbose_name="Option choisie",
    )
    category = models.CharField(
        "Catégorie", max_length=10, choices=Dish.Category.choices
    )
    portions = models.PositiveIntegerField("Portions", default=1)

    class Meta:
        ordering = ["category"]
        verbose_name = "Ligne de réservation"
        verbose_name_plural = "Lignes de réservation"
        constraints = [
            models.UniqueConstraint(
                fields=["reservation", "category"],
                name="reservations_unique_item_category_per_reservation",
            ),
        ]

    def __str__(self):
        return f"{self.option.dish.name} ×{self.portions}"


class DishRating(models.Model):
    """Notation de 1 à 5 étoiles une seule fois par réservation servie."""

    reservation = models.OneToOneField(
        Reservation,
        on_delete=models.CASCADE,
        related_name="rating",
        verbose_name="Réservation",
    )
    score = models.PositiveSmallIntegerField("Note (1 à 5)")
    created_at = models.DateTimeField("Noté le", auto_now_add=True)

    class Meta:
        verbose_name = "Note de plat"
        verbose_name_plural = "Notes de plats"
        constraints = [
            models.CheckConstraint(
                condition=Q(score__gte=1, score__lte=5),
                name="reservations_rating_score_1_to_5",
            ),
        ]

    def __str__(self):
        return f"Note {self.score}/5 — {self.reservation}"
