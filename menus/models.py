from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class Allergen(models.Model):
    name = models.CharField("Nom", max_length=100, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Allergène"
        verbose_name_plural = "Allergènes"

    def __str__(self):
        return self.name


class Regime(models.Model):
    name = models.CharField("Nom", max_length=100, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Régime alimentaire"
        verbose_name_plural = "Régimes alimentaires"

    def __str__(self):
        return self.name


class Dish(models.Model):
    class Category(models.TextChoices):
        ENTREE = "ENTREE", "Entrée"
        PLAT = "PLAT", "Plat principal"
        DESSERT = "DESSERT", "Dessert"

    name = models.CharField("Nom du plat", max_length=140, unique=True)
    category = models.CharField(
        "Catégorie", max_length=10, choices=Category.choices
    )
    description = models.TextField("Description", blank=True)
    ingredients = models.TextField("Ingrédients", blank=True)
    image = models.CharField(
        "Fichier image (static/img/dishes/)", max_length=160, blank=True
    )
    allergens = models.ManyToManyField(
        Allergen,
        blank=True,
        related_name="dishes",
        verbose_name="Allergènes",
    )
    compatible_regimes = models.ManyToManyField(
        Regime,
        blank=True,
        related_name="dishes",
        verbose_name="Régimes compatibles",
    )
    is_active = models.BooleanField("Actif", default=True)

    class Meta:
        ordering = ["category", "name"]
        verbose_name = "Plat"
        verbose_name_plural = "Plats"

    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"


class MealService(models.Model):
    class ServiceType(models.TextChoices):
        DEJEUNER = "DEJEUNER", "Déjeuner"

    date = models.DateField("Date du service")
    service_type = models.CharField(
        "Type de service",
        max_length=20,
        choices=ServiceType.choices,
        default=ServiceType.DEJEUNER,
    )
    is_published = models.BooleanField("Publié", default=False)
    reservation_deadline = models.DateTimeField(
        "Heure limite de réservation", blank=True
    )
    meal_price = models.PositiveIntegerField("Prix du repas complet (FCFA)")
    extra_portion_price = models.PositiveIntegerField(
        "Prix portion supplémentaire (FCFA)",
        null=True,
        blank=True,
        help_text="Laisser vide si aucune portion supplémentaire n'est proposée.",
    )
    closed_at = models.DateTimeField("Clôturé le", null=True, blank=True)

    class Meta:
        ordering = ["date", "service_type"]
        verbose_name = "Service de repas"
        verbose_name_plural = "Services de repas"
        constraints = [
            models.UniqueConstraint(
                fields=["date", "service_type"],
                name="menus_unique_service_date_type",
            ),
            models.CheckConstraint(
                condition=Q(meal_price__gt=0),
                name="menus_service_meal_price_gt_0",
            ),
            models.CheckConstraint(
                condition=(
                    Q(extra_portion_price__isnull=True)
                    | Q(extra_portion_price__gt=0)
                ),
                name="menus_service_extra_price_null_or_gt_0",
            ),
        ]

    @staticmethod
    def compute_deadline(service_date):
        cutoff_hour = getattr(settings, "RESERVATION_CUTOFF_HOUR", 18)
        naive_dt = datetime.combine(
            service_date - timedelta(days=1),
            time(hour=cutoff_hour, minute=0),
        )
        return timezone.make_aware(naive_dt, timezone.get_current_timezone())

    def clean(self):
        super().clean()
        if self.meal_price is not None and self.meal_price <= 0:
            raise ValidationError(
                {"meal_price": "Le prix du repas doit être strictement positif."}
            )
        if self.extra_portion_price is not None and self.extra_portion_price <= 0:
            raise ValidationError(
                {
                    "extra_portion_price": (
                        "Le prix de la portion supplémentaire doit être strictement positif."
                    )
                }
            )

    def save(self, *args, **kwargs):
        if not self.reservation_deadline and self.date:
            self.reservation_deadline = self.compute_deadline(self.date)
        super().save(*args, **kwargs)

    @property
    def is_open_for_reservation(self):
        return self.is_published and timezone.now() < self.reservation_deadline

    def __str__(self):
        return f"{self.get_service_type_display()} du {self.date:%d/%m/%Y}"


class MealOption(models.Model):
    service = models.ForeignKey(
        MealService,
        on_delete=models.CASCADE,
        related_name="options",
        verbose_name="Service",
    )
    dish = models.ForeignKey(
        Dish,
        on_delete=models.PROTECT,
        related_name="meal_options",
        verbose_name="Plat",
    )
    capacity = models.PositiveIntegerField("Capacité (portions)")
    reserved_count = models.PositiveIntegerField("Portions réservées", default=0)

    class Meta:
        ordering = ["dish__category", "dish__name"]
        verbose_name = "Option du service"
        verbose_name_plural = "Options du service"
        constraints = [
            models.UniqueConstraint(
                fields=["service", "dish"],
                name="menus_unique_option_service_dish",
            ),
            models.CheckConstraint(
                condition=Q(capacity__gt=0),
                name="menus_option_capacity_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(reserved_count__lte=F("capacity")),
                name="menus_option_reserved_lte_capacity",
            ),
        ]

    def clean(self):
        super().clean()
        if self.capacity is not None and self.capacity <= 0:
            raise ValidationError(
                {"capacity": "La capacité doit être supérieure à zéro."}
            )
        if self.reserved_count > (self.capacity or 0):
            raise ValidationError(
                {
                    "capacity": (
                        "La capacité ne peut pas être inférieure aux portions déjà réservées."
                    )
                }
            )

    @property
    def remaining(self):
        return max(0, self.capacity - self.reserved_count)

    @property
    def category(self):
        return self.dish.category

    def __str__(self):
        return f"{self.dish.name} — {self.service}"
