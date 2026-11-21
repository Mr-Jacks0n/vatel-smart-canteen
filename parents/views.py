from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import parent_required
from accounts.forms import DietaryProfileForm
from accounts.models import DietaryProfile, ParentLink, User
from payments.models import Payment
from payments.services import create_payment
from reservations.models import Reservation
from reservations.services import pay_now_scheduled
from wallet.models import Wallet
from wallet.services import (
    get_active_pass,
    get_projected_balance,
    get_scheduled_debit_total,
    get_school_year_bounds,
    update_debit_settings,
)


def _get_linked_child_or_404(parent: User, child_id: int) -> User:
    """Filtre strict par lien parent-enfant, sinon renvoie 404."""
    link = (
        ParentLink.objects.filter(parent=parent, child_id=child_id)
        .select_related("child")
        .first()
    )
    if not link:
        raise Http404("Enfant introuvable.")
    return link.child


@parent_required
def parent_home_view(request):
    links = (
        ParentLink.objects.filter(parent=request.user)
        .select_related("child")
        .order_by("child__first_name")
    )
    today = timezone.localdate()
    low_threshold = getattr(settings, "LOW_BALANCE_THRESHOLD", 2000)

    children_cards = []
    for link in links:
        child = link.child
        wallet, _ = Wallet.objects.get_or_create(user=child)
        active_pass = get_active_pass(child)
        next_res = (
            Reservation.objects.filter(
                beneficiary=child,
                service__date__gte=today,
                status=Reservation.Status.CONFIRMED,
            )
            .select_related("service")
            .order_by("service__date")
            .first()
        )
        children_cards.append(
            {
                "child": child,
                "wallet": wallet,
                "active_pass": active_pass,
                "is_low_balance": (not active_pass) and wallet.balance < low_threshold,
                "scheduled_total": get_scheduled_debit_total(child),
                "projected_balance": get_projected_balance(wallet),
                "next_res": next_res,
            }
        )

    return render(
        request,
        "parents/home.html",
        {"children_cards": children_cards},
    )


@parent_required
def child_detail_view(request, child_id: int):
    child = _get_linked_child_or_404(request.user, child_id)
    wallet, _ = Wallet.objects.get_or_create(user=child)
    active_pass = get_active_pass(child)
    profile, _ = DietaryProfile.objects.get_or_create(user=child)

    if request.method == "POST" and request.POST.get("action") == "dietary":
        dietary_form = DietaryProfileForm(request.POST, instance=profile)
        if dietary_form.is_valid():
            dietary_form.save()
            messages.success(
                request, f"Profil alimentaire de {child.full_name} mis à jour."
            )
            return redirect("parents:child_detail", child_id=child.pk)
    else:
        dietary_form = DietaryProfileForm(instance=profile)

    reservations = (
        Reservation.objects.filter(beneficiary=child)
        .select_related("service")
        .prefetch_related("items__option__dish")[:30]
    )
    wallet_txs = wallet.transactions.select_related("payment")[:30]
    payments = Payment.objects.filter(beneficiary=child).order_by("-created_at")[:30]

    school_year, valid_from, valid_until = get_school_year_bounds()
    topup_methods = [
        (Payment.Method.WAVE, "Wave"),
        (Payment.Method.ORANGE_MONEY, "Orange Money"),
        (Payment.Method.MTN_MOMO, "MTN MoMo"),
        (Payment.Method.MOOV_MONEY, "Moov Money"),
        (Payment.Method.BANK_CARD, "Carte bancaire"),
    ]
    annual_methods = topup_methods + [(Payment.Method.BANK_TRANSFER, "Virement bancaire")]

    return render(
        request,
        "parents/child_detail.html",
        {
            "child": child,
            "wallet": wallet,
            "active_pass": active_pass,
            "scheduled_total": get_scheduled_debit_total(child),
            "projected_balance": get_projected_balance(wallet),
            "reservations": reservations,
            "wallet_txs": wallet_txs,
            "payments": payments,
            "dietary_form": dietary_form,
            "topup_amounts": getattr(settings, "TOPUP_AMOUNTS", [1000, 2000, 5000, 10000, 20000]),
            "topup_methods": topup_methods,
            "annual_methods": annual_methods,
            "annual_pass_price": getattr(settings, "ANNUAL_PASS_PRICE", 180000),
            "school_year": school_year,
            "valid_from": valid_from,
            "valid_until": valid_until,
        },
    )


@parent_required
@require_POST
def child_topup_view(request, child_id: int):
    child = _get_linked_child_or_404(request.user, child_id)
    if request.POST.get("confirm_child") != "on":
        messages.error(
            request,
            f"Veuillez confirmer que vous rechargez le compte de {child.full_name}.",
        )
        return redirect("parents:child_detail", child_id=child.pk)
    try:
        payment = create_payment(
            kind=Payment.Kind.TOPUP,
            beneficiary=child,
            payer=request.user,
            method=request.POST.get("method", ""),
            amount=request.POST.get("amount"),
            phone_number=request.POST.get("phone_number", ""),
        )
        return redirect("payments:simulate", reference=payment.reference)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("parents:child_detail", child_id=child.pk)


@parent_required
@require_POST
def child_annual_prepayment_view(request, child_id: int):
    child = _get_linked_child_or_404(request.user, child_id)
    if request.POST.get("confirm_child") != "on":
        messages.error(
            request,
            f"Veuillez confirmer le prépaiement annuel pour {child.full_name}.",
        )
        return redirect("parents:child_detail", child_id=child.pk)
    try:
        payment = create_payment(
            kind=Payment.Kind.ANNUAL_PREPAYMENT,
            beneficiary=child,
            payer=request.user,
            method=request.POST.get("method", ""),
            phone_number=request.POST.get("phone_number", ""),
        )
        return redirect("payments:simulate", reference=payment.reference)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("parents:child_detail", child_id=child.pk)


@parent_required
@require_POST
def child_debit_settings_view(request, child_id: int):
    child = _get_linked_child_or_404(request.user, child_id)
    freq = request.POST.get("debit_frequency", Wallet.DebitFrequency.DAILY)
    auto_enabled = request.POST.get("auto_debit_enabled") == "on"
    try:
        update_debit_settings(child, freq, auto_enabled)
        messages.success(
            request, f"Réglages de débit mis à jour pour {child.full_name}."
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("parents:child_detail", child_id=child.pk)


@parent_required
@require_POST
def child_pay_now_view(request, child_id: int):
    child = _get_linked_child_or_404(request.user, child_id)
    try:
        settled = pay_now_scheduled(child, actor=request.user)
        messages.success(
            request,
            f"{len(settled)} repas programmé(s) réglé(s) pour {child.full_name}.",
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("parents:child_detail", child_id=child.pk)
