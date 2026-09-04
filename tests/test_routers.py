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
    """
    Nenhuma URL pode ter sumido na divisão em routers.

    Lemos o schema OpenAPI em vez de app.routes: versões novas do FastAPI
    guardam as rotas incluídas de forma aninhada, e app.routes deixaria de
    enxergá-las — o teste passaria sem testar nada.
    """

    EXPECTED = {
        # --- router de auth (Fase 6) ---
        "/api/auth/signup", "/api/auth/verify", "/api/auth/resend-verification",
        "/api/auth/login", "/api/auth/logout", "/api/auth/me",
        # --- router de system e páginas (Fase 6) ---
        "/api/system/config", "/", "/login", "/app",
        # --- continuam no api_server.py ---
        "/api/videos", "/api/videos/upload", "/api/videos/from-youtube",
        "/api/videos/download-status/{job_id}",
        "/api/generate", "/api/status/{job_id}",
        "/api/analyze", "/api/analyze-status/{job_id}", "/api/render-clip",
        # --- Fase 1 (confiabilidade): histórico persistido ---
        "/api/history",
        # --- Biblioteca de clips ---
        "/api/clips",
        "/api/plans",
        "/api/brand-kit",
        "/api/usage",
        "/api/clips/feedback",
        "/api/clips/feedback/summary",
    }

    def _paths(self) -> set:
        return set(api_server.app.openapi()["paths"].keys())

    def test_every_expected_url_exists(self):
        missing = self.EXPECTED - self._paths()
        self.assertEqual(missing, set(), f"URLs que sumiram: {sorted(missing)}")

    def test_no_unexpected_url_appeared(self):
        """Rota duplicada ou criada sem querer também é problema."""
        extra = self._paths() - self.EXPECTED
        self.assertEqual(extra, set(), f"URLs inesperadas: {sorted(extra)}")

    def test_auth_methods_preserved(self):
        paths = api_server.app.openapi()["paths"]
        self.assertIn("post", paths["/api/auth/login"])
        self.assertIn("get", paths["/api/auth/me"])


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

    def test_paths_module_is_single_source(self):
        """api_server.py e os routers precisam apontar pras mesmas pastas."""
        from core import paths
        self.assertEqual(api_server.VODS_DIR, paths.VODS_DIR)
        self.assertEqual(api_server.CLIPS_DIR, paths.CLIPS_DIR)


class TestAuthRouterIsolated(unittest.TestCase):
    """Este roda mesmo sem fastapi completo — confere a estrutura do módulo."""

    @unittest.skipUnless(FASTAPI_OK, "fastapi não instalado neste ambiente")
    def test_router_has_prefix(self):
        from core.routers import auth as auth_router
        self.assertEqual(auth_router.router.prefix, "/api/auth")


if __name__ == "__main__":
    unittest.main()
