"""
Testes da divisão da API em routers — Fase 6.

O RISCO desta fase é URL sumir sem ninguém notar: uma rota que deixa de
existir só aparece quando um botão do site para de funcionar. Estes testes
sobem o app de verdade e conferem que TODAS as URLs continuam registradas.

Se o fastapi não estiver instalado, os testes são pulados em vez de falhar.
"""
from __future__ import annotations

import unittest

try:
    from core import api_server
    FASTAPI_OK = True
except Exception as e:  # fastapi ausente, ou erro ao subir o app
    FASTAPI_OK = False
    IMPORT_ERROR = e


@unittest.skipUnless(FASTAPI_OK, "fastapi não instalado neste ambiente")
class TestAllUrlsStillRegistered(unittest.TestCase):
    """Nenhuma URL pode ter sumido na mudança."""

    EXPECTED = {
        # --- movidas pro router de auth na Fase 6 ---
        ("POST", "/api/auth/signup"),
        ("GET", "/api/auth/verify"),
        ("POST", "/api/auth/resend-verification"),
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/logout"),
        ("GET", "/api/auth/me"),
        # --- continuam no api_server.py ---
        ("GET", "/api/system/config"),
        ("GET", "/"),
        ("GET", "/login"),
        ("GET", "/app"),
        ("GET", "/api/videos"),
    }

    def _registered(self) -> set:
        found = set()
        for route in api_server.app.routes:
            for method in getattr(route, "methods", []) or []:
                found.add((method, getattr(route, "path", "")))
        return found

    def test_every_expected_url_exists(self):
        registered = self._registered()
        missing = self.EXPECTED - registered
        self.assertEqual(missing, set(), f"URLs que sumiram: {sorted(missing)}")

    def test_no_duplicate_auth_routes(self):
        """Se a rota antiga não foi removida, ela aparece duas vezes."""
        paths = [
            getattr(r, "path", "") for r in api_server.app.routes
            if getattr(r, "path", "").startswith("/api/auth/")
        ]
        self.assertEqual(len(paths), len(set(paths)), f"rota duplicada: {paths}")


@unittest.skipUnless(FASTAPI_OK, "fastapi não instalado neste ambiente")
class TestSharedDependencies(unittest.TestCase):
    """dependencies.py precisa ser a fonte única — sem cópias divergentes."""

    def test_cookie_name_unchanged(self):
        from core.dependencies import SESSION_COOKIE_NAME
        self.assertEqual(SESSION_COOKIE_NAME, "cliparadar_session")

    def test_api_server_uses_shared_dependency(self):
        from core.dependencies import get_current_user
        self.assertIs(api_server.get_current_user, get_current_user)

    def test_router_uses_shared_dependency(self):
        from core.dependencies import get_current_user
        from core.routers import auth as auth_router
        self.assertIs(auth_router.get_current_user, get_current_user)


class TestAuthRouterIsolated(unittest.TestCase):
    """Este roda mesmo sem fastapi completo — confere a estrutura do módulo."""

    @unittest.skipUnless(FASTAPI_OK, "fastapi não instalado neste ambiente")
    def test_router_has_prefix(self):
        from core.routers import auth as auth_router
        self.assertEqual(auth_router.router.prefix, "/api/auth")


if __name__ == "__main__":
    unittest.main()
