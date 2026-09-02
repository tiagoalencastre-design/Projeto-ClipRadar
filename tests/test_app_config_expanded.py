"""
Testes da Fase 1 EXPANDIDA do core/app_config.py.

Este arquivo é ADICIONAL — o tests/test_app_config.py original continua
existindo e passando sem nenhuma alteração.

Roda com:
    python -m unittest tests.test_app_config_expanded -v
"""
from __future__ import annotations

import json
import os
import unittest

from core import app_config


class _EnvIsolated(unittest.TestCase):
    """Guarda e restaura as variáveis de ambiente que os testes mexem."""

    ENV_VARS = (
        "CLIPRADAR_MODE",
        "CLIPRADAR_AI_PROVIDER",
        "CLIPRADAR_AI_TIMEOUT",
        "CLIPRADAR_AI_MAX_RETRIES",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OMNIROUTE_API_KEY",
        "OMNIROUTE_BASE_URL",
        "APP_BASE_URL",
    )

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in self.ENV_VARS}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestSecretsNeverLeak(_EnvIsolated):
    """
    O teste mais importante do arquivo: /api/system/config é PÚBLICO.
    Se uma chave de API aparecer no as_dict(), ela vaza pra internet.
    """

    FAKE_KEY = "sk-proj-CHAVE_FALSA_DE_TESTE_NAO_USAR_1234567890"

    def test_api_key_never_appears_in_as_dict(self):
        os.environ["CLIPRADAR_MODE"] = "development"
        os.environ["OPENAI_API_KEY"] = self.FAKE_KEY
        data = app_config.get_app_config().as_dict()
        serialized = json.dumps(data)
        self.assertNotIn(self.FAKE_KEY, serialized)
        self.assertNotIn("sk-proj", serialized)

    def test_as_dict_is_json_serializable(self):
        """Se não for serializável, o endpoint quebra em produção."""
        data = app_config.get_app_config().as_dict()
        json.dumps(data)  # não pode levantar exceção

    def test_has_api_key_reports_boolean_not_value(self):
        os.environ["CLIPRADAR_MODE"] = "development"
        os.environ["OPENAI_API_KEY"] = self.FAKE_KEY
        data = app_config.get_app_config().as_dict()
        self.assertIs(data["ai"]["has_api_key"], True)

    def test_has_api_key_false_when_absent(self):
        os.environ["CLIPRADAR_MODE"] = "development"
        os.environ.pop("OPENAI_API_KEY", None)
        data = app_config.get_app_config().as_dict()
        self.assertIs(data["ai"]["has_api_key"], False)


class TestGetAiApiKey(_EnvIsolated):
    """A trava de gasto: modo mock nunca devolve chave."""

    FAKE_KEY = "sk-proj-CHAVE_FALSA_DE_TESTE"

    def test_returns_key_in_development(self):
        os.environ["CLIPRADAR_MODE"] = "development"
        os.environ["OPENAI_API_KEY"] = self.FAKE_KEY
        self.assertEqual(app_config.get_ai_api_key(), self.FAKE_KEY)

    def test_returns_none_in_mock_even_with_real_key(self):
        os.environ["CLIPRADAR_MODE"] = "mock"
        os.environ["OPENAI_API_KEY"] = self.FAKE_KEY
        self.assertIsNone(app_config.get_ai_api_key())

    def test_returns_none_when_no_key_configured(self):
        os.environ["CLIPRADAR_MODE"] = "development"
        os.environ.pop("OPENAI_API_KEY", None)
        self.assertIsNone(app_config.get_ai_api_key())

    def test_empty_string_key_treated_as_absent(self):
        os.environ["CLIPRADAR_MODE"] = "development"
        os.environ["OPENAI_API_KEY"] = "   "
        self.assertIsNone(app_config.get_ai_api_key())


class TestModeAliases(_EnvIsolated):
    """'test' foi pedido no plano; 'mock' já existia. Os dois valem."""

    def test_test_is_alias_for_mock(self):
        os.environ["CLIPRADAR_MODE"] = "test"
        config = app_config.get_app_config()
        self.assertEqual(config.mode, "mock")
        self.assertFalse(config.flags.ai_processing_enabled)

    def test_mock_still_works(self):
        os.environ["CLIPRADAR_MODE"] = "mock"
        self.assertEqual(app_config.get_app_config().mode, "mock")

    def test_prod_alias(self):
        os.environ["CLIPRADAR_MODE"] = "prod"
        self.assertEqual(app_config.get_app_config().mode, "production")

    def test_uppercase_and_spaces_tolerated(self):
        os.environ["CLIPRADAR_MODE"] = "  MOCK  "
        self.assertEqual(app_config.get_app_config().mode, "mock")


class TestAIProviderSelection(_EnvIsolated):
    def test_defaults_to_openai(self):
        os.environ.pop("CLIPRADAR_AI_PROVIDER", None)
        self.assertEqual(app_config.get_app_config().ai.provider, "openai")

    def test_omniroute_uses_own_key_var_and_base_url(self):
        os.environ["CLIPRADAR_AI_PROVIDER"] = "omniroute"
        ai = app_config.get_app_config().ai
        self.assertEqual(ai.provider, "omniroute")
        self.assertEqual(ai.api_key_env_var, "OMNIROUTE_API_KEY")
        self.assertIsNotNone(ai.base_url)

    def test_unknown_provider_falls_back_to_openai(self):
        os.environ["CLIPRADAR_AI_PROVIDER"] = "provider_que_nao_existe"
        self.assertEqual(app_config.get_app_config().ai.provider, "openai")

    def test_every_task_has_a_model(self):
        tasks = app_config.get_app_config().ai.tasks
        for name in ("title", "edit_plan", "classification", "complex_reasoning"):
            self.assertTrue(getattr(tasks, name), f"tarefa '{name}' sem modelo")

    def test_invalid_timeout_does_not_crash(self):
        os.environ["CLIPRADAR_AI_TIMEOUT"] = "trinta"
        self.assertEqual(app_config.get_app_config().ai.timeout_seconds, 30)


class TestBackwardCompatibility(_EnvIsolated):
    """
    Garante que quem já usava o app_config continua funcionando:
    api_server.py usa .mode e .as_dict()['flags'];
    pipeline.py usa .flags.ai_processing_enabled.
    """

    def test_api_server_boot_contract(self):
        config = app_config.get_app_config()
        self.assertIsInstance(config.mode, str)
        self.assertIsInstance(config.as_dict()["flags"], dict)

    def test_pipeline_contract(self):
        config = app_config.get_app_config()
        self.assertIsInstance(config.flags.ai_processing_enabled, bool)

    def test_all_original_flags_still_exist(self):
        flags = app_config.get_app_config().as_dict()["flags"]
        for name in (
            "ai_processing_enabled",
            "video_processing_enabled",
            "auto_clipping_enabled",
            "captions_enabled",
            "mcp_enabled",
            "payments_enabled",
            "analytics_enabled",
        ):
            self.assertIn(name, flags, f"flag original '{name}' sumiu")


class TestNewConfigSections(_EnvIsolated):
    def test_all_sections_present_in_as_dict(self):
        data = app_config.get_app_config().as_dict()
        for section in ("ai", "pipeline", "storage", "queue", "observability", "base_url"):
            self.assertIn(section, data)

    def test_disabled_things_stay_disabled(self):
        """Nada de produção pode ligar sozinho nesta fase."""
        for mode in ("development", "mock", "production"):
            os.environ["CLIPRADAR_MODE"] = mode
            config = app_config.get_app_config()
            self.assertFalse(config.flags.cloud_storage_enabled, mode)
            self.assertFalse(config.flags.distributed_queue_enabled, mode)
            self.assertFalse(config.flags.structured_logging_enabled, mode)
            self.assertFalse(config.flags.credits_enabled, mode)
            self.assertEqual(config.storage.backend, "local", mode)
            self.assertEqual(config.queue.backend, "thread", mode)

    def test_limits_match_values_hardcoded_in_api_server(self):
        """Os números têm que bater com os que já estão no api_server.py,
        senão o comportamento muda quando a Fase 6 passar a usar daqui."""
        config = app_config.get_app_config()
        self.assertEqual(config.pipeline.max_concurrent_jobs, 2)
        self.assertEqual(config.pipeline.job_expiry_seconds, 24 * 60 * 60)
        self.assertEqual(config.storage.max_upload_size_bytes, 2 * 1024 * 1024 * 1024)

    def test_base_url_strips_trailing_slash(self):
        os.environ["APP_BASE_URL"] = "http://exemplo.com/"
        self.assertEqual(app_config.get_app_config().base_url, "http://exemplo.com")


if __name__ == "__main__":
    unittest.main()
