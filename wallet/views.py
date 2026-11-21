from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import diner_required
from payments.models import Payment
from payments.services import create_payment

from .models import Wallet
from .services import (
    get_active_pass,
    get_projected_balance,
    get_scheduled_debit_total,
    update_debit_settings,
)


@diner_required
def wallet_home_view(request):
    user = request.user
    active_pass = get_active_pass(user)
    wallet, _ = Wallet.objects.get_or_create(user=user)

    if active_pass:
        # 4.4 : élève sous forfait ne voit aucun montant de solde ni recharge ponctuelle
        return render(
            request,
            "wallet/wallet_home.html",
            {
                "active_pass": active_pass,
                "wallet": None,
            },
        )

    scheduled_total = get_scheduled_debit_total(user)
    projected_balance = get_projected_balance(wallet)
    low_threshold = getattr(settings, "LOW_BALANCE_THRESHOLD", 2000)

    tx_list = wallet.transactions.select_related("payment").all()
    paginator = Paginator(tx_list, 15)
    page_obj = paginator.get_page(request.GET.get("page"))

    topup_methods = [
        (Payment.Method.WAVE, "Wave"),
        (Payment.Method.ORANGE_MONEY, "Orange Money"),
        (Payment.Method.MTN_MOMO, "MTN MoMo"),
        (Payment.Method.MOOV_MONEY, "Moov Money"),
        (Payment.Method.BANK_CARD, "Carte bancaire"),
    ]

    return render(
        request,
        "wallet/wallet_home.html",
        {
            "active_pass": None,
            "wallet": wallet,
            "scheduled_total": scheduled_total,
            "projected_balance": projected_balance,
            "is_low_balance": wallet.balance < low_threshold,
            "low_threshold": low_threshold,
            "topup_amounts": getattr(settings, "TOPUP_AMOUNTS", [1000, 2000, 5000, 10000, 20000]),
            "topup_methods": topup_methods,
            "page_obj": page_obj,
        },
    )


@diner_required
@require_POST
def wallet_topup_init_view(request):
    method = request.POST.get("method", "")
    amount = request.POST.get("amount")
    phone_number = request.POST.get("phone_number", "")
    try:
        payment = create_payment(
            kind=Payment.Kind.TOPUP,
            beneficiary=request.user,
            payer=request.user,
            method=method,
            amount=amount,
            phone_number=phone_number,
        )
        return redirect("payments:simulate", reference=payment.reference)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("wallet:home")


@diner_required
@require_POST
def wallet_settings_view(request):
    debit_frequency = request.POST.get("debit_frequency", Wallet.DebitFrequency.DAILY)
    auto_debit_enabled = request.POST.get("auto_debit_enabled") == "on"
    try:
        update_debit_settings(request.user, debit_frequency, auto_debit_enabled)
        messages.success(request, "Vos réglages de débit ont été enregistrés.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("wallet:home")
