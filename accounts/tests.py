from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from menus.models import Allergen, Regime

from .models import Department, DietaryProfile, User


class AccountsAuthTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.first()
        self.eleve = User.objects.create_user(
            email="eleve@vatel.test",
            password="PasswordSolide123!",
            first_name="Aya",
            last_name="Kouassi",
            role=User.Role.ELEVE,
        )
        self.parent = User.objects.create_user(
            email="parent@vatel.test",
            password="PasswordSolide123!",
            first_name="Marc",
            last_name="Kouassi",
            role=User.Role.PARENT,
        )
        self.equipe = User.objects.create_user(
            email="equipe@vatel.test",
            password="PasswordSolide123!",
            first_name="Chef",
            last_name="Yao",
            role=User.Role.EQUIPE,
        )
        self.admin = User.objects.create_superuser(
            email="admin@vatel.test",
            password="PasswordSolide123!",
            first_name="Admin",
            last_name="Vatel",
        )

    def test_initial_referentials_loaded(self):
        self.assertGreaterEqual(Allergen.objects.count(), 9)
        self.assertGreaterEqual(Regime.objects.count(), 6)
        self.assertGreaterEqual(Department.objects.count(), 1)

    def test_registration_creates_eleve_and_ignores_role_field(self):
        """L'inscription publique crée un élève et son profil alimentaire ; tout champ role est ignoré."""
        response = self.client.post(
            reverse("accounts:register"),
            {
                "first_name": "Koffi",
                "last_name": "Bamba",
                "email": "koffi@vatel.test",
                "password1": "MotDePasseSolide99!",
                "password2": "MotDePasseSolide99!",
                "role": "ADMIN",
                "is_staff": "true",
                "is_superuser": "true",
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="koffi@vatel.test")
        self.assertEqual(user.role, User.Role.ELEVE)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(DietaryProfile.objects.filter(user=user).exists())
        self.assertTrue(user.password.startswith("argon2$"))

    def test_anonymous_redirected_to_login_on_private_pages(self):
        """Un visiteur anonyme est redirigé vers la page de connexion sur toute page privée."""
        for url_name in ("accounts:profile", "canteen:kitchen", "dashboard:home"):
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse("accounts:login"), response.url)

    def test_eleve_and_parent_receive_403_on_canteen_and_admin(self):
        """Les rôles Élève et Parent reçoivent une erreur 403 sur les espaces équipe et administration."""
        for user in (self.eleve, self.parent):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("canteen:kitchen")).status_code, 403)
            self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 403)

        self.client.force_login(self.equipe)
        self.assertEqual(self.client.get(reverse("canteen:kitchen")).status_code, 200)
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 403)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("canteen:kitchen")).status_code, 200)
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 200)

    def test_personnel_requires_department(self):
        """Un compte Personnel sans département ou direction est refusé."""
        with self.assertRaises(ValidationError):
            User.objects.create_user(
                email="staff-nodept@vatel.test",
                password="PasswordSolide123!",
                first_name="Paul",
                last_name="Ndiaye",
                role=User.Role.PERSONNEL,
                department=None,
            )

        staff = User.objects.create_user(
            email="staff-ok@vatel.test",
            password="PasswordSolide123!",
            first_name="Paul",
            last_name="Ndiaye",
            role=User.Role.PERSONNEL,
            department=self.dept,
        )
        self.assertEqual(staff.department, self.dept)
        self.assertTrue(DietaryProfile.objects.filter(user=staff).exists())

    def test_post_without_csrf_rejected(self):
        """Les requêtes POST sans jeton CSRF sont rejetées."""
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(
            reverse("accounts:login"),
            {"email": "eleve@vatel.test", "password": "PasswordSolide123!"},
        )
        self.assertEqual(response.status_code, 403)

    def test_logout_requires_post(self):
        self.client.force_login(self.eleve)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.assertEqual(self.client.post(reverse("accounts:logout")).status_code, 302)

    def test_registration_and_login_with_matricule(self):
        """Inscription avec Matricule Vatel (school_id) et connexion directe par Matricule."""
        resp = self.client.post(
            reverse("accounts:register"),
            {
                "school_id": "vtl-2026-777",
                "first_name": "Koffi",
                "last_name": "Bamba",
                "class_name": "Bachelor 3",
                "email": "koffi.bamba@vatel.ci",
                "password1": "VatelPass2026!",
                "password2": "VatelPass2026!",
            },
        )
        self.assertEqual(resp.status_code, 302)
        user = User.objects.get(email="koffi.bamba@vatel.ci")
        self.assertEqual(user.school_id, "VTL-2026-777")
        self.assertEqual(user.class_name, "Bachelor 3")

        self.client.logout()
        login_resp = self.client.post(
            reverse("accounts:login"),
            {
                "email": "VTL-2026-777",
                "password": "VatelPass2026!",
            },
        )
        self.assertEqual(login_resp.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
