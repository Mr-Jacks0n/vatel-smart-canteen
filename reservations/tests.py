from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import DietaryProfile, ParentLink, User
from core.models import Notification
from menus.models import Allergen, Dish, MealOption, MealService
from payments.models import Payment
from payments.services import confirm_payment, create_payment
from wallet.models import Wallet, WalletTransaction
from wallet.services import activate_annual_pass, debit_consumption

from .models import Reservation
from .services import (
    cancel_reservation,
    decline_day,
    modify_reservation,
    reserve,
)


class ReservationsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin-res@vatel.test",
            password="PasswordSolide123!",
            first_name="Admin",
            last_name="Res",
        )
        self.parent = User.objects.create_user(
            email="parent-res@vatel.test",
            password="PasswordSolide123!",
            first_name="Parent",
            last_name="One",
            role=User.Role.PARENT,
        )
        self.eleve = User.objects.create_user(
            email="eleve1@vatel.test",
            password="PasswordSolide123!",
            first_name="Aya",
            last_name="Koné",
            role=User.Role.ELEVE,
        )
        self.other_eleve = User.objects.create_user(
            email="eleve2@vatel.test",
            password="PasswordSolide123!",
            first_name="Yao",
            last_name="Brou",
            role=User.Role.ELEVE,
        )
        ParentLink.objects.create(
            parent=self.parent, child=self.eleve, created_by=self.admin
        )

        # Créditer eleve de 5 000 FCFA
        topup = create_payment(
            kind=Payment.Kind.TOPUP,
            beneficiary=self.eleve,
            payer=self.eleve,
            method=Payment.Method.WAVE,
            amount=5000,
        )
        confirm_payment(topup.reference, actor=self.eleve)

        self.peanut = Allergen.objects.get(name="arachides")
        self.entree = Dish.objects.create(name="Salade verte", category=Dish.Category.ENTREE)
        self.entree2 = Dish.objects.create(name="Velouté", category=Dish.Category.ENTREE)
        self.plat = Dish.objects.create(name="Mafé poulet", category=Dish.Category.PLAT)
        self.plat.allergens.add(self.peanut)
        self.plat2 = Dish.objects.create(name="Riz poisson", category=Dish.Category.PLAT)
        self.dessert = Dish.objects.create(name="Mangue fraîche", category=Dish.Category.DESSERT)

        self.service = MealService.objects.create(
            date=timezone.localdate() + timedelta(days=3),
            meal_price=1500,
            extra_portion_price=500,
            is_published=True,
        )
        self.opt_entree = MealOption.objects.create(service=self.service, dish=self.entree, capacity=10)
        self.opt_entree2 = MealOption.objects.create(service=self.service, dish=self.entree2, capacity=10)
        self.opt_plat = MealOption.objects.create(service=self.service, dish=self.plat, capacity=10)
        self.opt_plat2 = MealOption.objects.create(service=self.service, dish=self.plat2, capacity=1)
        self.opt_dessert = MealOption.objects.create(service=self.service, dish=self.dessert, capacity=10)

    def test_idor_ticket_returns_404(self):
        """Ouvrir le ticket d'un autre élève renvoie une erreur 404."""
        res = reserve(
            self.eleve,
            self.service.pk,
            [self.opt_entree.pk, self.opt_plat2.pk, self.opt_dessert.pk],
        )
        self.client.force_login(self.other_eleve)
        resp = self.client.get(reverse("reservations:ticket", args=[res.ticket_token]))
        self.assertEqual(resp.status_code, 404)

    def test_wallet_reservation_scheduled_no_immediate_debit(self):
        """Une réservation par portefeuille est programmée à la veille sans débit immédiat et incrémente les portions."""
        res = reserve(
            self.eleve,
            self.service.pk,
            [self.opt_entree.pk, self.opt_plat.pk, self.opt_dessert.pk],
            extra_portions=1,
            fulfillment=Reservation.Fulfillment.DELIVERY,
            delivery_location="Bâtiment A, Salle 102",
        )
        self.assertEqual(res.status, Reservation.Status.CONFIRMED)
        self.assertEqual(res.payment_mode, Reservation.PaymentMode.WALLET)
        self.assertEqual(res.payment_status, Reservation.PaymentStatus.SCHEDULED)
        self.assertEqual(res.total_price, 1500 + 500 + settings.DELIVERY_FEE)
        self.assertEqual(Wallet.objects.get(user=self.eleve).balance, 5000)
        self.opt_plat.refresh_from_db()
        self.assertEqual(self.opt_plat.reserved_count, 2)

    def test_mandatory_plat_no_duplicate_category_skip_starter_dessert(self):
        """Une réservation sans plat principal ou avec doublon de catégorie est refusée ; Sans entrée/dessert reste au prix complet."""
        with self.assertRaises(ValidationError):
            reserve(self.eleve, self.service.pk, [self.opt_entree.pk])

        with self.assertRaises(ValidationError):
            reserve(
                self.eleve,
                self.service.pk,
                [self.opt_entree.pk, self.opt_entree2.pk, self.opt_plat.pk],
            )

        res = reserve(
            self.eleve,
            self.service.pk,
            [self.opt_plat.pk],
            skip_starter=True,
            skip_dessert=True,
        )
        self.assertTrue(res.skip_starter)
        self.assertTrue(res.skip_dessert)
        self.assertEqual(res.total_price, 1500)

    def test_double_reservation_refused(self):
        """Une double réservation sur un même service est refusée."""
        reserve(self.eleve, self.service.pk, [self.opt_plat.pk])
        with self.assertRaises(ValidationError):
            reserve(self.eleve, self.service.pk, [self.opt_plat.pk])

    def test_full_option_unpublished_or_past_deadline_refused(self):
        """Une option complète, un service non publié ou une heure limite dépassée sont refusés."""
        reserve(self.eleve, self.service.pk, [self.opt_plat2.pk])
        with self.assertRaises(ValidationError):
            reserve(self.other_eleve, self.service.pk, [self.opt_plat2.pk])

        closed_service = MealService.objects.create(
            date=timezone.localdate(),
            meal_price=1500,
            is_published=True,
            reservation_deadline=timezone.now() - timedelta(hours=1),
        )
        opt_closed = MealOption.objects.create(service=closed_service, dish=self.plat, capacity=5)
        with self.assertRaises(ValidationError):
            reserve(self.other_eleve, closed_service.pk, [opt_closed.pk])

    def test_allergen_alert_requires_server_acknowledgment(self):
        """L'alerte allergène est refusée sans confirmation et acceptée/tracée avec confirmation."""
        profile = DietaryProfile.objects.get(user=self.eleve)
        profile.allergies.add(self.peanut)

        with self.assertRaises(ValidationError):
            reserve(self.eleve, self.service.pk, [self.opt_plat.pk], allergy_acknowledged=False)

        res = reserve(self.eleve, self.service.pk, [self.opt_plat.pk], allergy_acknowledged=True)
        self.assertTrue(res.allergy_acknowledged)

    def test_annual_pass_reservation_settled_and_balance_hidden(self):
        """Sous forfait actif : réservation réglée sans mouvement de portefeuille et solde non affiché."""
        activate_annual_pass(self.other_eleve, actor=self.admin, reason="Test forfait")
        res = reserve(self.other_eleve, self.service.pk, [self.opt_plat.pk])
        self.assertEqual(res.payment_mode, Reservation.PaymentMode.PASS)
        self.assertEqual(res.payment_status, Reservation.PaymentStatus.SETTLED)
        self.assertEqual(res.amount_due_at_pickup, 0)
        self.assertEqual(WalletTransaction.objects.filter(wallet__user=self.other_eleve).count(), 0)

        self.client.force_login(self.other_eleve)
        resp = self.client.get(reverse("wallet:home"))
        self.assertContains(resp, "Année soldée")
        self.assertNotContains(resp, "Solde Vatel Cantine")

    def test_insufficient_projected_balance_notifies_and_pickup_limit(self):
        """Un solde prévisionnel insuffisant envoie une notification préventive ; la limite de réservations au retrait est respectée."""
        reserve(self.other_eleve, self.service.pk, [self.opt_plat.pk])
        self.assertTrue(
            Notification.objects.filter(
                user=self.other_eleve, kind=Notification.Kind.INSUFFICIENT_BALANCE
            ).exists()
        )

        # Limite MAX_UNPAID_RESERVATIONS (2)
        for day_offset in (4, 5):
            svc = MealService.objects.create(
                date=timezone.localdate() + timedelta(days=day_offset),
                meal_price=1500,
                is_published=True,
            )
            opt = MealOption.objects.create(service=svc, dish=self.plat, capacity=10)
            reserve(
                self.eleve,
                svc.pk,
                [opt.pk],
                payment_mode_choice=Reservation.PaymentMode.PICKUP,
            )

        svc3 = MealService.objects.create(
            date=timezone.localdate() + timedelta(days=6),
            meal_price=1500,
            is_published=True,
        )
        opt3 = MealOption.objects.create(service=svc3, dish=self.plat, capacity=10)
        with self.assertRaises(ValidationError):
            reserve(
                self.eleve,
                svc3.pk,
                [opt3.pk],
                payment_mode_choice=Reservation.PaymentMode.PICKUP,
            )

    def test_cancel_and_modify(self):
        """Annulation avant l'heure limite (remboursement unique si déjà débité) et modification atomique."""
        res = reserve(self.eleve, self.service.pk, [self.opt_plat.pk])
        cancel_reservation(self.eleve, res.pk)
        self.opt_plat.refresh_from_db()
        self.assertEqual(self.opt_plat.reserved_count, 0)
        self.assertEqual(Wallet.objects.get(user=self.eleve).balance, 5000)

        # Cas déjà débité (hebdomadaire)
        res2 = reserve(self.eleve, self.service.pk, [self.opt_plat.pk])
        debit_consumption(self.eleve, res2.total_price, actor=self.admin, reservation=res2)
        res2.payment_status = Reservation.PaymentStatus.SETTLED
        res2.save(update_fields=["payment_status"])
        self.assertEqual(Wallet.objects.get(user=self.eleve).balance, 3500)

        cancel_reservation(self.eleve, res2.pk)
        self.assertEqual(Wallet.objects.get(user=self.eleve).balance, 5000)

        # Modification de réservation
        res3 = reserve(self.eleve, self.service.pk, [self.opt_plat.pk])
        res4 = modify_reservation(
            self.eleve,
            res3.pk,
            option_ids=[self.opt_entree.pk, self.opt_plat.pk],
            extra_portions=1,
        )
        self.opt_plat.refresh_from_db()
        self.assertEqual(self.opt_plat.reserved_count, 2)
        self.assertEqual(res4.total_price, 2000)

    def test_decline_day(self):
        """La déclaration « Je ne mange pas ce jour » est non facturée, bloque une réservation simultanée et reste modifiable avant clôture."""
        dec = decline_day(self.eleve, self.service.pk)
        self.assertEqual(dec.status, Reservation.Status.DECLINED)
        self.assertEqual(dec.total_price, 0)
        self.assertIsNone(dec.ticket_token)

        with self.assertRaises(ValidationError):
            reserve(self.eleve, self.service.pk, [self.opt_plat.pk])

        cancel_reservation(self.eleve, dec.pk)
        res = reserve(self.eleve, self.service.pk, [self.opt_plat.pk])
        self.assertEqual(res.status, Reservation.Status.CONFIRMED)

    def test_extra_portion_and_delivery_for_pass_holder(self):
        """La portion supplémentaire et la livraison ne sont pas couvertes par le forfait annuel, et le lieu de livraison est obligatoire."""
        activate_annual_pass(self.other_eleve, actor=self.admin, reason="Test")

        with self.assertRaises(ValidationError):
            reserve(
                self.other_eleve,
                self.service.pk,
                [self.opt_plat.pk],
                fulfillment=Reservation.Fulfillment.DELIVERY,
                delivery_location="",
            )

        res = reserve(
            self.other_eleve,
            self.service.pk,
            [self.opt_plat.pk],
            extra_portions=1,
            fulfillment=Reservation.Fulfillment.DELIVERY,
            delivery_location="Bureau Direction",
        )
        self.assertEqual(res.payment_mode, Reservation.PaymentMode.PASS)
        self.assertEqual(res.payment_status, Reservation.PaymentStatus.TO_PAY_AT_PICKUP)
        self.assertEqual(res.delivery_fee_paid, settings.DELIVERY_FEE)
        self.assertEqual(res.amount_due_at_pickup, 500 + settings.DELIVERY_FEE)
