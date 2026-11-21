from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import User

from .models import Payment
from .providers import get_provider
from .services import confirm_payment, fail_payment


def _get_accessible_payment(user, reference: str) -> Payment:
    payment = get_object_or_404(
        Payment.objects.select_related("beneficiary", "payer"),
        reference=reference,
    )
    if (
        payment.payer_id != user.id
        and payment.beneficiary_id != user.id
        and user.role != User.Role.ADMIN
    ):
        raise Http404("Paiement introuvable.")
    return payment


def _redirect_after_payment(payment: Payment, user: User):
    if user.role == User.Role.PARENT:
        return redirect("parents:home")
    if payment.kind == Payment.Kind.PICKUP:
        return redirect("reservations:list")
    return redirect("wallet:home")


@login_required
def simulate_payment_view(request, reference: str):
    payment = _get_accessible_payment(request.user, reference)
    instructions = get_provider(payment.method).get_instructions(payment)
    return render(
        request,
        "payments/simulate.html",
        {
            "payment": payment,
            "instructions": instructions,
        },
    )


@login_required
@require_POST
def simulate_confirm_view(request, reference: str):
    payment = _get_accessible_payment(request.user, reference)
    if payment.method == Payment.Method.BANK_TRANSFER:
        messages.error(
            request,
            "Un virement bancaire ne peut être confirmé que par l'administration.",
        )
        return redirect("payments:simulate", reference=payment.reference)
    try:
        confirmed = confirm_payment(payment.reference, actor=request.user)
        messages.success(
            request,
            f"Paiement confirmé ({confirmed.reference}) — {confirmed.amount} FCFA.",
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return _redirect_after_payment(payment, request.user)


@login_required
@require_POST
def simulate_fail_view(request, reference: str):
    payment = _get_accessible_payment(request.user, reference)
    try:
        fail_payment(payment.reference, actor=request.user)
        messages.warning(request, "Paiement simulé en échec.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return _redirect_after_payment(payment, request.user)
