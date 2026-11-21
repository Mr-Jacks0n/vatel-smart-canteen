from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, ParentLink, User
from menus.models import Dish, MealOption, MealService
from payments.models import Payment
from payments.services import confirm_payment, create_payment
from reservations.models import Reservation
from reservations.services import reserve

from .services import get_financial_report, get_operational_stats


class DashboardReportsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin-d@vatel.test",
            password="PasswordSolide123!",
            first_name="Admin",
            last_name="Dash",
        )
        self.dept = Department.objects.first()
        self.staff = User.objects.create_user(
            email="staff-d@vatel.test",
            password="PasswordSolide123!",
            first_name="Claire",
            last_name="Mory",
            role=User.Role.PERSONNEL,
            department=self.dept,
        )
        self.parent = User.objects.create_user(
            email="parent-d@vatel.test",
            password="PasswordSolide123!",
            first_name="Parent",
            last_name="D",
            role=User.Role.PARENT,
        )
        self.eleve = User.objects.create_user(
            email="eleve-d@vatel.test",
            password="PasswordSolide123!",
            first_name="Junior",
            last_name="D",
            role=User.Role.ELEVE,
        )
        ParentLink.objects.create(
            parent=self.parent, child=self.eleve, created_by=self.admin
        )
        self.plat = Dish.objects.create(name="Yassa poulet", category=Dish.Category.PLAT)
        self.svc = MealService.objects.create(
            date=timezone.localdate() + timedelta(days=1),
            meal_price=1500,
            is_published=True,
        )
        self.opt = MealOption.objects.create(service=self.svc, dish=self.plat, capacity=10)

    def test_financial_separation_and_department_stats(self):
        """Les trois encaissements sont séparés, le solde des portefeuilles est hors recette et les statistiques par département sont exactes."""
        # 1. Recharge TOPUP 5000
        p_topup = create_payment(
            kind=Payment.Kind.TOPUP,
            beneficiary=self.staff,
            payer=self.staff,
            method=Payment.Method.WAVE,
            amount=5000,
        )
        confirm_payment(p_topup.reference, actor=self.staff)

        # 2. Prépaiement annuel
        p_ann = create_payment(
            kind=Payment.Kind.ANNUAL_PREPAYMENT,
            beneficiary=self.eleve,
            payer=self.parent,
            method=Payment.Method.BANK_CARD,
        )
        confirm_payment(p_ann.reference, actor=self.parent)

        # 3. Paiement au retrait PICKUP 1500
        res_staff = reserve(
            self.staff,
            self.svc.pk,
            [self.opt.pk],
            payment_mode_choice=Reservation.PaymentMode.PICKUP,
        )
        p_pickup = create_payment(
            kind=Payment.Kind.PICKUP,
            beneficiary=self.staff,
            payer=self.staff,
            method=Payment.Method.ORANGE_MONEY,
            reservation=res_staff,
        )
        confirm_payment(p_pickup.reference, actor=self.staff)

        fin = get_financial_report(period="day")
        self.assertEqual(fin["topup_total"], 5000)
        self.assertEqual(fin["annual_total"], settings.ANNUAL_PASS_PRICE)
        self.assertEqual(fin["pickup_total"], 1500)
        self.assertEqual(
            fin["total_collected"], 5000 + settings.ANNUAL_PASS_PRICE + 1500
        )
        self.assertEqual(fin["total_wallet_balances"], 5000)

        ops = get_operational_stats()
        dept_row = next(d for d in ops["dept_stats"] if d["id"] == self.dept.id)
        self.assertEqual(dept_row["staff_count"], 1)
        self.assertEqual(dept_row["reservations_count"], 1)
