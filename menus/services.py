"""Services métier de gestion des menus et capacités."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Dish, MealOption, MealService


def get_two_weeks_window(reference_date=None):
    """Retourne la fenêtre du lundi de la semaine courante au vendredi de la semaine suivante."""
    today = reference_date or timezone.localdate()
    monday_current = today - timedelta(days=today.weekday())
    friday_next = monday_current + timedelta(days=11)
    return monday_current, friday_next


def get_week_services(reference_date=None, published_only=True):
    start_date, end_date = get_two_weeks_window(reference_date)
    qs = MealService.objects.filter(date__range=(start_date, end_date)).prefetch_related(
        "options__dish__allergens",
        "options__dish__compatible_regimes",
    )
    if published_only:
        qs = qs.filter(is_published=True)
    return list(qs.order_by("date"))


def group_options_by_category(service):
    grouped = {
        Dish.Category.ENTREE: [],
        Dish.Category.PLAT: [],
        Dish.Category.DESSERT: [],
    }
    for opt in service.options.select_related("dish").prefetch_related(
        "dish__allergens", "dish__compatible_regimes"
    ):
        grouped.setdefault(opt.dish.category, []).append(opt)
    return grouped


def _has_active_reservations(service):
    has_res = (
        hasattr(service, "reservations")
        and service.reservations.exclude(status="CANCELLED").exists()
    )
    return has_res or service.options.filter(reserved_count__gt=0).exists()


@transaction.atomic
def toggle_publish_service(service, publish: bool):
    service = MealService.objects.select_for_update().get(pk=service.pk)
    if not publish and _has_active_reservations(service):
        raise ValidationError(
            "Impossible de dépublier un service qui possède des réservations actives."
        )
    service.is_published = publish
    service.save(update_fields=["is_published"])
    return service


@transaction.atomic
def update_option_capacity(option, new_capacity: int):
    option = MealOption.objects.select_for_update().get(pk=option.pk)
    if new_capacity <= 0:
        raise ValidationError("La capacité doit être supérieure à zéro.")
    if new_capacity < option.reserved_count:
        raise ValidationError(
            f"Impossible de réduire la capacité sous {option.reserved_count} portions déjà réservées."
        )
    option.capacity = new_capacity
    option.save(update_fields=["capacity"])
    return option


@transaction.atomic
def delete_option(option):
    option = MealOption.objects.select_for_update().get(pk=option.pk)
    if option.reserved_count > 0:
        raise ValidationError(
            "Impossible de supprimer une option déjà réservée."
        )
    option.delete()
