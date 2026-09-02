"""
Testes do core/app_config.py — Fase 1.

Roda com:
    python -m unittest tests.test_app_config -v
"""
from __future__ import annotations

import importlib
import os
import unittest


def _reload_app_config():
    """O módulo lê a variável de ambiente na hora que a função é chamada
    (não no import), então normalmente nem precisaria recarregar — mas
    recarregamos mesmo assim, por segurança, caso isso mude no futuro."""
    from core import app_config
    importlib.reload(app_config)
    return app_config


class TestAppConfig(unittest.TestCase):
    def setUp(self):
        # guarda o valor original pra não vazar entre testes
        self._original_mode = os.environ.get("CLIPRADAR_MODE")

    def tearDown(self):
        if self._original_mode is None:
            os.environ.pop("CLIPRADAR_MODE", None)
        else:
            os.environ["CLIPRADAR_MODE"] = self._original_mode

    def test_default_mode_is_development_when_env_var_absent(self):
        os.environ.pop("CLIPRADAR_MODE", None)
        app_config = _reload_app_config()
        config = app_config.get_app_config()
        self.assertEqual(config.mode, "development")

    def test_invalid_mode_falls_back_to_development(self):
        os.environ["CLIPRADAR_MODE"] = "isso_nao_existe"
        app_config = _reload_app_config()
        config = app_config.get_app_config()
        self.assertEqual(config.mode, "development")

    def test_development_mode_allows_ai_processing_flag(self):
        os.environ["CLIPRADAR_MODE"] = "development"
        app_config = _reload_app_config()
        config = app_config.get_app_config()
        self.assertTrue(config.flags.ai_processing_enabled)

    def test_mock_mode_blocks_ai_processing_flag(self):
        os.environ["CLIPRADAR_MODE"] = "mock"
        app_config = _reload_app_config()
        config = app_config.get_app_config()
        self.assertFalse(config.flags.ai_processing_enabled)

    def test_production_mode_currently_behaves_like_development(self):
        os.environ["CLIPRADAR_MODE"] = "production"
        app_config = _reload_app_config()
        config = app_config.get_app_config()
        self.assertTrue(config.flags.ai_processing_enabled)

    def test_video_processing_never_blocked_by_any_mode(self):
        app_config = _reload_app_config()
        for mode in ("development", "mock", "production"):
            os.environ["CLIPRADAR_MODE"] = mode
            config = app_config.get_app_config()
            self.assertTrue(config.flags.video_processing_enabled, f"falhou no modo {mode}")

    def test_mcp_payments_analytics_always_false_in_every_mode(self):
        app_config = _reload_app_config()
        for mode in ("development", "mock", "production"):
            os.environ["CLIPRADAR_MODE"] = mode
            config = app_config.get_app_config()
            self.assertFalse(config.flags.mcp_enabled, f"MCP deveria estar False no modo {mode}")
            self.assertFalse(config.flags.payments_enabled, f"payments deveria estar False no modo {mode}")
            self.assertFalse(config.flags.analytics_enabled, f"analytics deveria estar False no modo {mode}")

    def test_as_dict_returns_expected_shape(self):
        os.environ["CLIPRADAR_MODE"] = "development"
        app_config = _reload_app_config()
        config = app_config.get_app_config()
        data = config.as_dict()
        self.assertIn("mode", data)
        self.assertIn("flags", data)
        self.assertIsInstance(data["flags"], dict)
        self.assertIn("ai_processing_enabled", data["flags"])


if __name__ == "__main__":
    unittest.main()
