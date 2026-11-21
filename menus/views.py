from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import admin_required
from accounts.models import DietaryProfile

from .forms import MealOptionForm, MealServiceForm
from .models import Dish, MealOption, MealService
from .services import (
    delete_option,
    get_week_services,
    group_options_by_category,
    toggle_publish_service,
    update_option_capacity,
)


def week_menu_view(request):
    """Menu public et élève de la semaine courante et suivante."""
    services = get_week_services(published_only=True)
    selected_service = None
    selected_date = request.GET.get("date")
    if services:
        if selected_date:
            selected_service = next(
                (s for s in services if s.date.isoformat() == selected_date),
                services[0],
            )
        else:
            selected_service = services[0]

    grouped_options = (
        group_options_by_category(selected_service) if selected_service else {}
    )

    user_allergy_ids = set()
    user_intolerance_ids = set()
    user_regime_ids = set()
    if request.user.is_authenticated and request.user.is_diner:
        profile = DietaryProfile.objects.filter(user=request.user).prefetch_related(
            "allergies", "intolerances", "regimes"
        ).first()
        if profile:
            user_allergy_ids = set(profile.allergies.values_list("id", flat=True))
            user_intolerance_ids = set(profile.intolerances.values_list("id", flat=True))
            user_regime_ids = set(profile.regimes.values_list("id", flat=True))

    user_reservation = None
    if (
        selected_service
        and request.user.is_authenticated
        and request.user.is_diner
        and hasattr(selected_service, "reservations")
    ):
        user_reservation = (
            selected_service.reservations.filter(beneficiary=request.user)
            .exclude(status="CANCELLED")
            .first()
        )

    categories = [
        (Dish.Category.ENTREE, "Entrées", grouped_options.get(Dish.Category.ENTREE, [])),
        (Dish.Category.PLAT, "Plats principaux", grouped_options.get(Dish.Category.PLAT, [])),
        (Dish.Category.DESSERT, "Desserts", grouped_options.get(Dish.Category.DESSERT, [])),
    ]

    return render(
        request,
        "menus/week_menu.html",
        {
            "services": services,
            "selected_service": selected_service,
            "categories": categories,
            "user_allergy_ids": user_allergy_ids,
            "user_intolerance_ids": user_intolerance_ids,
            "user_regime_ids": user_regime_ids,
            "user_reservation": user_reservation,
        },
    )


@admin_required
def admin_service_list_view(request):
    services = MealService.objects.prefetch_related("options__dish").order_by("-date")
    if request.method == "POST":
        form = MealServiceForm(request.POST)
        if form.is_valid():
            service = form.save()
            messages.success(request, f"Service du {service.date:%d/%m/%Y} créé.")
            return redirect("menus:admin_service_detail", service_id=service.pk)
    else:
        form = MealServiceForm()
    return render(
        request,
        "menus/admin_service_list.html",
        {"services": services, "form": form},
    )


@admin_required
def admin_service_detail_view(request, service_id):
    service = get_object_or_404(MealService, pk=service_id)
    if request.method == "POST":
        option_form = MealOptionForm(request.POST)
        if option_form.is_valid():
            option = option_form.save(commit=False)
            option.service = service
            try:
                option.full_clean()
                option.save()
                messages.success(request, f"Plat « {option.dish.name} » ajouté au service.")
                return redirect("menus:admin_service_detail", service_id=service.pk)
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
    else:
        option_form = MealOptionForm()

    grouped = group_options_by_category(service)
    categories = [
        (Dish.Category.ENTREE, "Entrées", grouped.get(Dish.Category.ENTREE, [])),
        (Dish.Category.PLAT, "Plats principaux", grouped.get(Dish.Category.PLAT, [])),
        (Dish.Category.DESSERT, "Desserts", grouped.get(Dish.Category.DESSERT, [])),
    ]
    return render(
        request,
        "menus/admin_service_detail.html",
        {
            "service": service,
            "categories": categories,
            "option_form": option_form,
        },
    )


@admin_required
@require_POST
def admin_service_toggle_publish_view(request, service_id):
    service = get_object_or_404(MealService, pk=service_id)
    try:
        updated = toggle_publish_service(service, not service.is_published)
        state = "publié" if updated.is_published else "dépublié"
        messages.success(request, f"Service du {updated.date:%d/%m/%Y} {state}.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("menus:admin_service_detail", service_id=service.pk)


@admin_required
@require_POST
def admin_option_update_capacity_view(request, option_id):
    option = get_object_or_404(MealOption, pk=option_id)
    try:
        new_cap = int(request.POST.get("capacity", 0))
        update_option_capacity(option, new_cap)
        messages.success(request, f"Capacité de « {option.dish.name} » mise à jour ({new_cap}).")
    except (ValueError, ValidationError) as exc:
        msg = " ".join(exc.messages) if isinstance(exc, ValidationError) else "Capacité invalide."
        messages.error(request, msg)
    return redirect("menus:admin_service_detail", service_id=option.service_id)


@admin_required
@require_POST
def admin_option_delete_view(request, option_id):
    option = get_object_or_404(MealOption, pk=option_id)
    service_id = option.service_id
    try:
        delete_option(option)
        messages.success(request, "Option supprimée du service.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("menus:admin_service_detail", service_id=service_id)
