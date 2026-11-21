from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import ParentLink, User
from core.models import Notification
from menus.models import Dish, MealOption, MealService
from payments.models import Payment
from payments.services import confirm_payment, create_payment
from reservations.models import Reservation
from reservations.services import cancel_reservation, pay_now_scheduled, reserve
from wallet.models import Wallet, WalletTransaction
from wallet.services import update_debit_settings

from .closure import run_closure
from .services import serve_reservation


class CanteenAndClosureTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin-c@vatel.test",
            password="PasswordSolide123!",
            first_name="Admin",
            last_name="C",
        )
        self.equipe = User.objects.create_user(
            email="equipe-c@vatel.test",
            password="PasswordSolide123!",
            first_name="Agent",
            last_name="Comptoir",
            role=User.Role.EQUIPE,
        )
        self.parent = User.objects.create_user(
            email="parent-c@vatel.test",
            password="PasswordSolide123!",
            first_name="Parent",
            last_name="C",
            role=User.Role.PARENT,
        )
        self.eleve = User.objects.create_user(
            email="eleve-c@vatel.test",
            password="PasswordSolide123!",
            first_name="Amina",
            last_name="Kouadio",
            role=User.Role.ELEVE,
        )
        self.other = User.objects.create_user(
            email="other-c@vatel.test",
            password="PasswordSolide123!",
            first_name="Benoit",
            last_name="Soro",
            role=User.Role.ELEVE,
        )
        ParentLink.objects.create(
            parent=self.parent, child=self.eleve, created_by=self.admin
        )
        self.plat = Dish.objects.create(name="Thiéboudienne", category=Dish.Category.PLAT)

    def _topup(self, user, amount):
        p = create_payment(
            kind=Payment.Kind.TOPUP,
            beneficiary=user,
            payer=user,
            method=Payment.Method.WAVE,
            amount=amount,
        )
        confirm_payment(p.reference, actor=user)

    def test_counter_payment_before_serve_and_no_double_serve(self):
        """Un ticket avec reste dû est bloqué avant confirmation du paiement et ne peut être servi qu'une seule fois."""
        today = timezone.localdate()
        svc = MealService.objects.create(
            date=today,
            meal_price=1500,
            is_published=True,
            reservation_deadline=timezone.now() + timedelta(hours=2),
        )
        opt = MealOption.objects.create(service=svc, dish=self.plat, capacity=10)
        res = reserve(
            self.eleve,
            svc.pk,
            [opt.pk],
            payment_mode_choice=Reservation.PaymentMode.PICKUP,
        )
        self.assertEqual(res.amount_due_at_pickup, 1500)

        # Impossible de servir tant que dû > 0
        with self.assertRaises(ValidationError):
            serve_reservation(res.pk, actor=self.equipe)

        # Un paiement au retrait pour la réservation d'un autre utilisateur est refusé
        with self.assertRaises(ValidationError):
            create_payment(
                kind=Payment.Kind.PICKUP,
                beneficiary=self.eleve,
                payer=self.other,
                method=Payment.Method.WAVE,
                reservation=res,
            )

        # Paiement PICKUP par le bénéficiaire -> SETTLED, portefeuille inchangé
        pay = create_payment(
            kind=Payment.Kind.PICKUP,
            beneficiary=self.eleve,
            payer=self.eleve,
            method=Payment.Method.WAVE,
            reservation=res,
        )
        confirm_payment(pay.reference, actor=self.eleve)
        res.refresh_from_db()
        self.assertEqual(res.payment_status, Reservation.PaymentStatus.SETTLED)
        self.assertEqual(res.amount_due_at_pickup, 0)
        self.assertEqual(Wallet.objects.get(user=self.eleve).balance, 0)

        # Service validé 1 fois, second passage refusé
        serve_reservation(res.pk, actor=self.equipe)
        res.refresh_from_db()
        self.assertEqual(res.status, Reservation.Status.SERVED)

        with self.assertRaises(ValidationError):
            serve_reservation(res.pk, actor=self.equipe)

    def test_daily_closure_idempotent(self):
        """La clôture journalière exécute un débit exact et reste idempotente en cas de double exécution."""
        self._topup(self.eleve, 5000)
        svc = MealService.objects.create(
            date=timezone.localdate() + timedelta(days=1),
            meal_price=1500,
            is_published=True,
            reservation_deadline=timezone.now() + timedelta(hours=1),
        )
        opt = MealOption.objects.create(service=svc, dish=self.plat, capacity=10)
        res = reserve(self.eleve, svc.pk, [opt.pk])

        # Exécuter clôture 2 fois
        s1 = run_closure(target_date=svc.date, force=True)
        s2 = run_closure(target_date=svc.date, force=True)

        self.assertEqual(s1["debited_count"], 1)
        self.assertEqual(s2["debited_count"], 0)
        self.assertEqual(Wallet.objects.get(user=self.eleve).balance, 3500)
        self.assertEqual(
            WalletTransaction.objects.filter(
                reservation=res, kind=WalletTransaction.Kind.CONSUMPTION
            ).count(),
            1,
        )

    def test_weekly_closure_and_refund_on_cancel(self):
        """La clôture hebdomadaire débite toute la semaine et une annulation avant l'heure limite rembourse exactement."""
        self._topup(self.eleve, 5000)
        update_debit_settings(self.eleve, Wallet.DebitFrequency.WEEKLY, True)

        today = timezone.localdate()
        next_monday = today + timedelta(days=(7 - today.weekday()))
        svc1 = MealService.objects.create(
            date=next_monday, meal_price=1500, is_published=True
        )
        svc2 = MealService.objects.create(
            date=next_monday + timedelta(days=1), meal_price=1500, is_published=True
        )
        opt1 = MealOption.objects.create(service=svc1, dish=self.plat, capacity=10)
        opt2 = MealOption.objects.create(service=svc2, dish=self.plat, capacity=10)

        res1 = reserve(self.eleve, svc1.pk, [opt1.pk])
        res2 = reserve(self.eleve, svc2.pk, [opt2.pk])

        summary = run_closure(target_date=svc1.date, force=True)
        self.assertEqual(summary["debited_count"], 2)
        self.assertEqual(Wallet.objects.get(user=self.eleve).balance, 2000)

        cancel_reservation(self.eleve, res2.pk)
        self.assertEqual(Wallet.objects.get(user=self.eleve).balance, 3500)
        res1.refresh_from_db()
        self.assertEqual(res1.payment_status, Reservation.PaymentStatus.SETTLED)

    def test_insufficient_balance_at_closure_fallback_and_cancel(self):
        """En cas de solde insuffisant à la clôture : débits chronologiques, repli en paiement au retrait ou annulation, et notifications."""
        self._topup(self.eleve, 2000)
        svc1 = MealService.objects.create(
            date=timezone.localdate() + timedelta(days=1),
            meal_price=1500,
            is_published=True,
        )
        svc2 = MealService.objects.create(
            date=timezone.localdate() + timedelta(days=2),
            meal_price=1500,
            is_published=True,
        )
        opt1 = MealOption.objects.create(service=svc1, dish=self.plat, capacity=10)
        opt2 = MealOption.objects.create(service=svc2, dish=self.plat, capacity=10)
        res1 = reserve(self.eleve, svc1.pk, [opt1.pk])
        res2 = reserve(self.eleve, svc2.pk, [opt2.pk])

        run_closure(force=True)
        res1.refresh_from_db()
        res2.refresh_from_db()
        self.assertEqual(res1.payment_status, Reservation.PaymentStatus.SETTLED)
        self.assertEqual(res2.payment_status, Reservation.PaymentStatus.TO_PAY_AT_PICKUP)
        self.assertEqual(res2.amount_due_at_pickup, 1500)
        self.assertTrue(
            Notification.objects.filter(
                user=self.parent, kind=Notification.Kind.INSUFFICIENT_BALANCE
            ).exists()
        )

        # Cas PICKUP_PAYMENT_ENABLED=False -> annulation + libération portion
        with override_settings(PICKUP_PAYMENT_ENABLED=False):
            svc3 = MealService.objects.create(
                date=timezone.localdate() + timedelta(days=3),
                meal_price=1500,
                is_published=True,
            )
            opt3 = MealOption.objects.create(service=svc3, dish=self.plat, capacity=10)
            res3 = reserve(self.other, svc3.pk, [opt3.pk])
            run_closure(target_date=svc3.date, force=True)
            res3.refresh_from_db()
            opt3.refresh_from_db()
            self.assertEqual(res3.status, Reservation.Status.CANCELLED)
            self.assertEqual(opt3.reserved_count, 0)

    def test_auto_debit_disabled_pay_now_and_fallback(self):
        """Lorsque le débit automatique est désactivé : règlement manuel avant clôture ou repli lors de la clôture."""
        self._topup(self.eleve, 5000)
        update_debit_settings(self.eleve, Wallet.DebitFrequency.DAILY, False)

        svc1 = MealService.objects.create(
            date=timezone.localdate() + timedelta(days=1),
            meal_price=1500,
            is_published=True,
        )
        opt1 = MealOption.objects.create(service=svc1, dish=self.plat, capacity=10)
        res1 = reserve(self.eleve, svc1.pk, [opt1.pk])

        pay_now_scheduled(self.eleve)
        res1.refresh_from_db()
        self.assertEqual(res1.payment_status, Reservation.PaymentStatus.SETTLED)
        self.assertEqual(Wallet.objects.get(user=self.eleve).balance, 3500)

        svc2 = MealService.objects.create(
            date=timezone.localdate() + timedelta(days=2),
            meal_price=1500,
            is_published=True,
        )
        opt2 = MealOption.objects.create(service=svc2, dish=self.plat, capacity=10)
        res2 = reserve(self.eleve, svc2.pk, [opt2.pk])
        run_closure(target_date=svc2.date, force=True)
        res2.refresh_from_db()
        self.assertEqual(res2.payment_status, Reservation.PaymentStatus.TO_PAY_AT_PICKUP)

    def test_delivery_validated_once_by_equipe(self):
        """Une livraison est validée une seule fois par l'équipe cantine avec le libellé 'Livré'."""
        self._topup(self.eleve, 5000)
        svc = MealService.objects.create(
            date=timezone.localdate(),
            meal_price=1500,
            is_published=True,
            reservation_deadline=timezone.now() + timedelta(hours=1),
        )
        opt = MealOption.objects.create(service=svc, dish=self.plat, capacity=10)
        res = reserve(
            self.eleve,
            svc.pk,
            [opt.pk],
            fulfillment=Reservation.Fulfillment.DELIVERY,
            delivery_location="Salle 105",
        )
        run_closure(target_date=svc.date, force=True)
        serve_reservation(res.pk, actor=self.equipe)
        res.refresh_from_db()
        self.assertEqual(res.status_display_label, "Livré")
        with self.assertRaises(ValidationError):
            serve_reservation(res.pk, actor=self.equipe)

    def test_csv_export_multi_day_and_rating(self):
        """Export CSV cuisine, réservation multi-jours et notation unique après service."""
        from django.urls import reverse
        from reservations.services import rate_reservation_dish, reserve_multiple_days

        self._topup(self.eleve, 10000)
        today = timezone.localdate()
        svc_today = MealService.objects.create(
            date=today,
            meal_price=1500,
            is_published=True,
            reservation_deadline=timezone.now() + timedelta(hours=2),
        )
        svc_d2 = MealService.objects.create(
            date=today + timedelta(days=2),
            meal_price=1500,
            is_published=True,
        )
        svc_d3 = MealService.objects.create(
            date=today + timedelta(days=3),
            meal_price=1500,
            is_published=True,
        )
        opt_today = MealOption.objects.create(service=svc_today, dish=self.plat, capacity=10)
        opt_d2 = MealOption.objects.create(service=svc_d2, dish=self.plat, capacity=10)
        opt_d3 = MealOption.objects.create(service=svc_d3, dish=self.plat, capacity=10)

        # Réservation multi-jours
        created = reserve_multiple_days(
            self.eleve,
            [
                {"service_id": svc_d2.pk, "option_ids": [opt_d2.pk]},
                {"service_id": svc_d3.pk, "option_ids": [opt_d3.pk]},
            ],
        )
        self.assertEqual(len(created), 2)

        # Export CSV cuisine — EQUIPE autorisé, ELEVE refusé (403)
        self.client.force_login(self.eleve)
        self.assertEqual(
            self.client.get(reverse("canteen:kitchen_export_csv")).status_code, 403
        )
        self.client.force_login(self.equipe)
        csv_resp = self.client.get(
            f"{reverse('canteen:kitchen_export_csv')}?date={svc_d2.date.isoformat()}"
        )
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn("text/csv", csv_resp["Content-Type"])
        self.assertContains(csv_resp, "Thiéboudienne")

        # Notation des plats : refusée avant service, acceptée une seule fois après service
        res_today = reserve(self.eleve, svc_today.pk, [opt_today.pk])
        with self.assertRaises(ValidationError):
            rate_reservation_dish(self.eleve, res_today.pk, 5)

        run_closure(target_date=svc_today.date, force=True)
        serve_reservation(res_today.pk, actor=self.equipe)
        rating = rate_reservation_dish(self.eleve, res_today.pk, 5)
        self.assertEqual(rating.score, 5)

        with self.assertRaises(ValidationError):
            rate_reservation_dish(self.eleve, res_today.pk, 4)
