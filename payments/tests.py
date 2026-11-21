from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import ParentLink, User
from core.models import Notification
from wallet.models import AnnualPass, Wallet, WalletTransaction
from wallet.services import debit_consumption, has_active_pass, refund_debit

from .models import Payment
from .services import confirm_payment, create_payment, fail_payment


class FinancialModuleTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin-fin@vatel.test",
            password="PasswordSolide123!",
            first_name="Admin",
            last_name="Fin",
        )
        self.parent = User.objects.create_user(
            email="parent-fin@vatel.test",
            password="PasswordSolide123!",
            first_name="Fatou",
            last_name="Diallo",
            role=User.Role.PARENT,
        )
        self.other_parent = User.objects.create_user(
            email="other-parent@vatel.test",
            password="PasswordSolide123!",
            first_name="Jean",
            last_name="Konan",
            role=User.Role.PARENT,
        )
        self.eleve = User.objects.create_user(
            email="eleve-fin@vatel.test",
            password="PasswordSolide123!",
            first_name="Moussa",
            last_name="Diallo",
            role=User.Role.ELEVE,
        )
        ParentLink.objects.create(
            parent=self.parent, child=self.eleve, created_by=self.admin
        )

    def test_topup_pending_idempotent_confirm_and_fail(self):
        """Une recharge en attente ne crédite pas le solde ; la confirmation est idempotente et l'échec notifie sans créditer."""
        wallet = Wallet.objects.get(user=self.eleve)
        self.assertEqual(wallet.balance, 0)

        payment = create_payment(
            kind=Payment.Kind.TOPUP,
            beneficiary=self.eleve,
            payer=self.eleve,
            method=Payment.Method.WAVE,
            amount=5000,
            phone_number="0701020304",
        )
        wallet.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(wallet.balance, 0)

        confirm_payment(payment.reference, actor=self.eleve)
        confirm_payment(payment.reference, actor=self.eleve)  # Idempotence
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, 5000)
        self.assertEqual(
            WalletTransaction.objects.filter(payment=payment).count(), 1
        )

        failed_payment = create_payment(
            kind=Payment.Kind.TOPUP,
            beneficiary=self.eleve,
            payer=self.eleve,
            method=Payment.Method.ORANGE_MONEY,
            amount=2000,
        )
        fail_payment(failed_payment.reference, actor=self.eleve)
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, 5000)
        self.assertTrue(
            Notification.objects.filter(
                user=self.eleve, kind=Notification.Kind.PAYMENT_FAILED
            ).exists()
        )

    def test_annual_prepayment_only_linked_parent_and_server_price(self):
        """Seul un parent lié peut souscrire au prépaiement annuel, au montant fixé par le serveur et sans doublon."""
        with self.assertRaises(ValidationError):
            create_payment(
                kind=Payment.Kind.ANNUAL_PREPAYMENT,
                beneficiary=self.eleve,
                payer=self.other_parent,
                method=Payment.Method.WAVE,
                amount=1,
            )

        payment = create_payment(
            kind=Payment.Kind.ANNUAL_PREPAYMENT,
            beneficiary=self.eleve,
            payer=self.parent,
            method=Payment.Method.BANK_CARD,
            amount=1,  # Falsifié : doit être ignoré par le serveur
        )
        self.assertEqual(payment.amount, settings.ANNUAL_PASS_PRICE)
        self.assertFalse(has_active_pass(self.eleve))

        confirm_payment(payment.reference, actor=self.parent)
        self.assertTrue(has_active_pass(self.eleve))
        self.assertEqual(Wallet.objects.get(user=self.eleve).balance, 0)

        with self.assertRaises(ValidationError):
            create_payment(
                kind=Payment.Kind.ANNUAL_PREPAYMENT,
                beneficiary=self.eleve,
                payer=self.parent,
                method=Payment.Method.WAVE,
            )

    def test_no_physical_method_and_bank_transfer_rules(self):
        """Aucun moyen physique n'est accepté ; le virement bancaire est réservé au prépaiement annuel et confirmé par un administrateur."""
        with self.assertRaises(ValidationError):
            create_payment(
                kind=Payment.Kind.TOPUP,
                beneficiary=self.eleve,
                payer=self.eleve,
                method="CASH",
                amount=2000,
            )

        with self.assertRaises(ValidationError):
            create_payment(
                kind=Payment.Kind.TOPUP,
                beneficiary=self.eleve,
                payer=self.eleve,
                method=Payment.Method.BANK_TRANSFER,
                amount=2000,
            )

        virement = create_payment(
            kind=Payment.Kind.ANNUAL_PREPAYMENT,
            beneficiary=self.eleve,
            payer=self.parent,
            method=Payment.Method.BANK_TRANSFER,
        )
        self.assertEqual(virement.status, Payment.Status.PENDING)

        with self.assertRaises(ValidationError):
            confirm_payment(virement.reference, actor=self.parent)

        confirm_payment(virement.reference, actor=self.admin)
        self.assertTrue(AnnualPass.objects.filter(student=self.eleve, payment=virement).exists())

    def test_low_balance_notification_once_for_student_and_parent(self):
        """Une notification de solde faible est envoyée à l'élève et au parent au franchissement du seuil, sans doublon."""
        topup = create_payment(
            kind=Payment.Kind.TOPUP,
            beneficiary=self.eleve,
            payer=self.parent,
            method=Payment.Method.WAVE,
            amount=5000,
        )
        confirm_payment(topup.reference, actor=self.parent)

        # Débit 3500 -> solde 1500 (< 2000) -> 1 notif élève + 1 notif parent
        tx1 = debit_consumption(self.eleve, 3500, actor=self.admin)
        self.assertEqual(
            Notification.objects.filter(
                user=self.eleve, kind=Notification.Kind.LOW_BALANCE
            ).count(),
            1,
        )
        self.assertEqual(
            Notification.objects.filter(
                user=self.parent, kind=Notification.Kind.LOW_BALANCE
            ).count(),
            1,
        )

        # Second débit sous le seuil -> pas de doublon
        debit_consumption(self.eleve, 500, actor=self.admin)
        self.assertEqual(
            Notification.objects.filter(
                user=self.eleve, kind=Notification.Kind.LOW_BALANCE
            ).count(),
            1,
        )

        # Remboursement unique
        refund_debit(tx1, actor=self.admin)
        with self.assertRaises(ValidationError):
            refund_debit(tx1, actor=self.admin)
