from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from .models import Allergen, Dish, MealOption, MealService, Regime
from .services import delete_option, toggle_publish_service, update_option_capacity


class MenusTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin-menu@vatel.test",
            password="PasswordSolide123!",
            first_name="Admin",
            last_name="Menus",
        )
        self.entree = Dish.objects.create(
            name="Salade avocat",
            category=Dish.Category.ENTREE,
            ingredients="Avocat, tomate, citron",
        )
        self.plat = Dish.objects.create(
            name="Poulet braisé attiéké",
            category=Dish.Category.PLAT,
            ingredients="Poulet, manioc, épices",
        )
        self.dessert = Dish.objects.create(
            name="Salade de fruits",
            category=Dish.Category.DESSERT,
            ingredients="Mangue, ananas, papaye",
        )
        self.plat.allergens.add(Allergen.objects.first())
        self.plat.compatible_regimes.add(Regime.objects.first())

    def test_meal_service_deadline_and_price_constraints(self):
        today = timezone.localdate()
        service = MealService.objects.create(
            date=today + timedelta(days=2),
            meal_price=1500,
            extra_portion_price=500,
            is_published=True,
        )
        self.assertEqual(service.reservation_deadline.hour, 18)
        self.assertEqual(service.reservation_deadline.date(), service.date - timedelta(days=1))

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MealService.objects.create(
                    date=today + timedelta(days=3),
                    meal_price=0,
                )

    def test_meal_option_constraints_and_protection_rules(self):
        today = timezone.localdate()
        service = MealService.objects.create(
            date=today + timedelta(days=2),
            meal_price=1500,
            is_published=True,
        )
        opt = MealOption.objects.create(service=service, dish=self.plat, capacity=10, reserved_count=4)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MealOption.objects.create(service=service, dish=self.plat, capacity=5)

        with self.assertRaises(ValidationError):
            update_option_capacity(opt, 3)

        update_option_capacity(opt, 12)
        opt.refresh_from_db()
        self.assertEqual(opt.capacity, 12)

        with self.assertRaises(ValidationError):
            delete_option(opt)

        with self.assertRaises(ValidationError):
            toggle_publish_service(service, False)

    def test_only_published_services_visible_in_week_menu(self):
        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday())
        svc_pub = MealService.objects.create(
            date=monday,
            meal_price=1500,
            is_published=True,
        )
        MealOption.objects.create(service=svc_pub, dish=self.plat, capacity=20)
        svc_draft = MealService.objects.create(
            date=monday + timedelta(days=1),
            meal_price=1500,
            is_published=False,
        )
        MealOption.objects.create(service=svc_draft, dish=self.entree, capacity=20)

        response = self.client.get(reverse("menus:week_menu"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Poulet braisé attiéké")
        self.assertNotContains(response, "Salade avocat")
        self.assertContains(response, "contamination croisée")
