from django.test import TestCase
from django.urls import reverse

from accounts.models import ParentLink, User
from payments.models import Payment
from wallet.services import has_active_pass


class ParentsSpaceTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin-p@vatel.test",
            password="PasswordSolide123!",
            first_name="Admin",
            last_name="P",
        )
        self.parent = User.objects.create_user(
            email="parent1@vatel.test",
            password="PasswordSolide123!",
            first_name="Awa",
            last_name="Touré",
            role=User.Role.PARENT,
        )
        self.child_linked = User.objects.create_user(
            email="child1@vatel.test",
            password="PasswordSolide123!",
            first_name="Kader",
            last_name="Touré",
            role=User.Role.ELEVE,
        )
        self.child_other = User.objects.create_user(
            email="child2@vatel.test",
            password="PasswordSolide123!",
            first_name="Sali",
            last_name="Coulibaly",
            role=User.Role.ELEVE,
        )
        ParentLink.objects.create(
            parent=self.parent, child=self.child_linked, created_by=self.admin
        )

    def test_parent_sees_linked_child_and_gets_404_for_unlinked(self):
        """Un parent voit son enfant lié et reçoit une erreur 404 pour un enfant non lié (détail et recharge)."""
        self.client.force_login(self.parent)
        resp_ok = self.client.get(
            reverse("parents:child_detail", args=[self.child_linked.pk])
        )
        self.assertEqual(resp_ok.status_code, 200)
        self.assertContains(resp_ok, "Kader Touré")

        resp_404 = self.client.get(
            reverse("parents:child_detail", args=[self.child_other.pk])
        )
        self.assertEqual(resp_404.status_code, 404)

        resp_topup_404 = self.client.post(
            reverse("parents:child_topup", args=[self.child_other.pk]),
            {"amount": 5000, "method": Payment.Method.WAVE, "confirm_child": "on"},
        )
        self.assertEqual(resp_topup_404.status_code, 404)

    def test_parent_annual_prepayment_full_flow(self):
        """Parcours parent complet : initiation et confirmation serveur activant le forfait annuel."""
        self.client.force_login(self.parent)
        resp = self.client.post(
            reverse("parents:child_annual_prepayment", args=[self.child_linked.pk]),
            {
                "method": Payment.Method.WAVE,
                "phone_number": "0700000000",
                "confirm_child": "on",
            },
        )
        self.assertEqual(resp.status_code, 302)
        payment = Payment.objects.get(
            beneficiary=self.child_linked, kind=Payment.Kind.ANNUAL_PREPAYMENT
        )
        self.assertEqual(payment.status, Payment.Status.PENDING)

        resp_confirm = self.client.post(
            reverse("payments:simulate_confirm", args=[payment.reference])
        )
        self.assertEqual(resp_confirm.status_code, 302)
        self.assertTrue(has_active_pass(self.child_linked))
