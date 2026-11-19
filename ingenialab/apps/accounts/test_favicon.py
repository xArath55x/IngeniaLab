"""Favicon en todas las páginas (ACT-313B; OBS-01): sin él, el navegador pide /favicon.ico y registra un 404."""
from django.contrib.staticfiles import finders

from apps.progress.tests import BaseCase


class FaviconTests(BaseCase):
    def test_pages_link_an_existing_icon(self):
        self.assertIsNotNone(finders.find("img/favicon.svg"))
        for url in ("/", "/elicitacion/", "/reportes/"):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), 'rel="icon"')
        self.client.logout()
        for url in ("/cuentas/login/", "/cuentas/registro/"):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), 'rel="icon"')

    def test_favicon_ico_redirects_to_static_icon(self):  # Revisión del PR #48: Safari no usa el SVG
        self.assertIsNotNone(finders.find("img/favicon.ico"))
        r = self.client.get("/favicon.ico")
        self.assertEqual(r.status_code, 301)
        self.assertTrue(r["Location"].endswith("img/favicon.ico"))
        self.assertContains(self.client.get("/elicitacion/"), 'favicon.ico" sizes="any"')
        self.client.logout()
        self.assertContains(self.client.get("/cuentas/login/"), 'favicon.ico" sizes="any"')
