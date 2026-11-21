from django.test import TestCase
from django.urls import reverse


class HomeViewTests(TestCase):
    def test_home_page_returns_200_and_security_headers(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vatel Smart Canteen")
        self.assertContains(response, "hx-headers=")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertIn("default-src 'self'", response["Content-Security-Policy"])

    def test_pwa_service_worker_and_offline_page(self):
        sw = self.client.get(reverse("core:service_worker"))
        self.assertEqual(sw.status_code, 200)
        self.assertIn("application/javascript", sw["Content-Type"])
        self.assertContains(sw, "/portefeuille/")
        self.assertContains(sw, "/menu/")

        offline = self.client.get(reverse("core:offline"))
        self.assertEqual(offline.status_code, 200)
        self.assertContains(offline, "Vous êtes hors ligne")
