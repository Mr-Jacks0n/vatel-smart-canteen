"""Prestataires de paiement simulés isolés derrière une interface commune."""

import secrets
from abc import ABC, abstractmethod

from django.conf import settings
from django.core.exceptions import ValidationError

from .models import Payment


class BasePaymentProvider(ABC):
    """Interface commune permettant de remplacer facilement la simulation par une API réelle."""

    @abstractmethod
    def generate_reference(self, kind: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_instructions(self, payment: Payment) -> dict:
        raise NotImplementedError


class SimulatedMobileMoneyProvider(BasePaymentProvider):
    def generate_reference(self, kind: str) -> str:
        prefix = {"TOPUP": "TOP", "ANNUAL_PREPAYMENT": "ANN", "PICKUP": "PKP"}.get(kind, "PAY")
        return f"VSC-{prefix}-{secrets.token_hex(4).upper()}"

    def get_instructions(self, payment: Payment) -> dict:
        return {
            "mode": "MOBILE_MONEY",
            "title": f"Validez le paiement {payment.get_method_display()} sur votre téléphone",
            "subtitle": "Paiement simulé — démonstration",
            "can_self_simulate": True,
            "details": (
                f"Demande envoyée vers {payment.phone_number or 'numéro de démonstration'} "
                f"pour un montant de {payment.amount} FCFA."
            ),
        }


class SimulatedBankCardProvider(BasePaymentProvider):
    """Carte bancaire simulée : aucune donnée de carte n'est jamais saisie ni stockée."""

    def generate_reference(self, kind: str) -> str:
        prefix = {"TOPUP": "TOP", "ANNUAL_PREPAYMENT": "ANN", "PICKUP": "PKP"}.get(kind, "PAY")
        return f"VSC-CB-{prefix}-{secrets.token_hex(4).upper()}"

    def get_instructions(self, payment: Payment) -> dict:
        return {
            "mode": "BANK_CARD",
            "title": "Validez le paiement par carte bancaire (simulé)",
            "subtitle": "Paiement simulé — démonstration (aucune donnée de carte saisie ni stockée)",
            "can_self_simulate": True,
            "details": f"Autorisation bancaire simulée pour {payment.amount} FCFA.",
        }


class SimulatedBankTransferProvider(BasePaymentProvider):
    """Virement bancaire (prépaiement annuel uniquement, confirmé par un ADMIN)."""

    def generate_reference(self, kind: str) -> str:
        return f"VSC-VIR-{secrets.token_hex(4).upper()}"

    def get_instructions(self, payment: Payment) -> dict:
        return {
            "mode": "BANK_TRANSFER",
            "title": "Effectuez le virement bancaire auprès de l'établissement",
            "subtitle": "Paiement simulé — confirmation par l'administration requise",
            "can_self_simulate": False,
            "details": getattr(
                settings,
                "BANK_TRANSFER_DETAILS",
                "Coordonnées bancaires Vatel (fictives en démonstration)",
            ),
            "reference_hint": f"Indiquez impérativement la référence {payment.reference} dans le libellé.",
        }


def get_provider(method: str) -> BasePaymentProvider:
    if method in Payment.MOBILE_MONEY_METHODS:
        return SimulatedMobileMoneyProvider()
    if method == Payment.Method.BANK_CARD:
        return SimulatedBankCardProvider()
    if method == Payment.Method.BANK_TRANSFER:
        return SimulatedBankTransferProvider()
    raise ValidationError(
        "Moyen de paiement non autorisé. Aucun paiement physique n'est accepté."
    )
