"""
Testes da camada de IA — Fases 3 e 4.

Nenhum teste faz chamada real de API. Tudo é simulado.

Roda com:
    python -m unittest tests.test_ai_providers -v
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from core import ai_title, edit_plan
from core.ai_providers import OpenAITextProvider, TextProvider, get_provider, is_ai_available
from core.ai_providers.base import TextResponse
from core.ai_providers.registry import get_model_for_task

FAKE_KEY = "sk-proj-CHAVE_FALSA_DE_TESTE"


class _EnvIsolated(unittest.TestCase):
    ENV = ("CLIPRADAR_MODE", "CLIPRADAR_AI_PROVIDER", "OPENAI_API_KEY",
           "OMNIROUTE_API_KEY", "OMNIROUTE_BASE_URL")

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in self.ENV}

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _enable_ai(self):
        os.environ["CLIPRADAR_MODE"] = "development"
        os.environ["OPENAI_API_KEY"] = FAKE_KEY


class TestRegistry(_EnvIsolated):
    def test_no_provider_without_key(self):
        os.environ["CLIPRADAR_MODE"] = "development"
        os.environ.pop("OPENAI_API_KEY", None)
        self.assertIsNone(get_provider("title"))
        self.assertFalse(is_ai_available())

    def test_no_provider_in_mock_mode_even_with_key(self):
        """A trava de gasto vale também aqui."""
        os.environ["CLIPRADAR_MODE"] = "mock"
        os.environ["OPENAI_API_KEY"] = FAKE_KEY
        self.assertIsNone(get_provider("title"))
        self.assertFalse(is_ai_available())

    def test_provider_available_in_development(self):
        self._enable_ai()
        provider = get_provider("title")
        self.assertIsInstance(provider, TextProvider)
        self.assertIsInstance(provider, OpenAITextProvider)

    def test_omniroute_provider_uses_its_base_url(self):
        os.environ["CLIPRADAR_MODE"] = "development"
        os.environ["CLIPRADAR_AI_PROVIDER"] = "omniroute"
        os.environ["OMNIROUTE_API_KEY"] = FAKE_KEY
        os.environ["OMNIROUTE_BASE_URL"] = "http://localhost:20128/v1"
        provider = get_provider("title")
        self.assertIsNotNone(provider)
        self.assertEqual(provider.name, "omniroute")
        self.assertEqual(provider._base_url, "http://localhost:20128/v1")

    def test_each_task_resolves_a_model(self):
        for task in ("title", "edit_plan", "classification", "complex_reasoning"):
            self.assertTrue(get_model_for_task(task))

    def test_unknown_task_falls_back(self):
        self.assertTrue(get_model_for_task("tarefa_inexistente"))


class TestOpenAIProvider(_EnvIsolated):
    def _fake_openai(self, content: str):
        """Simula a resposta da biblioteca openai."""
        response = MagicMock()
        response.choices[0].message.content = content
        response.usage.prompt_tokens = 120
        response.usage.completion_tokens = 8
        client = MagicMock()
        client.chat.completions.create.return_value = response
        return client

    def test_successful_call_returns_text_response(self):
        provider = OpenAITextProvider(api_key=FAKE_KEY)
        with patch.object(provider, "_client", return_value=self._fake_openai("CLUTCH INSANO")):
            result = provider.complete(system="s", user="u", model="gpt-4o-mini")
        self.assertIsInstance(result, TextResponse)
        self.assertEqual(result.text, "CLUTCH INSANO")
        self.assertEqual(result.total_tokens, 128)

    def test_api_failure_returns_none_instead_of_raising(self):
        provider = OpenAITextProvider(api_key=FAKE_KEY)
        with patch.object(provider, "_client", side_effect=Exception("sem crédito")):
            self.assertIsNone(provider.complete(system="s", user="u", model="m"))

    def test_empty_key_returns_none(self):
        provider = OpenAITextProvider(api_key="")
        self.assertIsNone(provider.complete(system="s", user="u", model="m"))

    def test_json_mode_sets_response_format(self):
        provider = OpenAITextProvider(api_key=FAKE_KEY)
        client = self._fake_openai('{"ok": true}')
        with patch.object(provider, "_client", return_value=client):
            provider.complete(system="s", user="u", model="m", json_mode=True)
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})

    def test_complete_text_shortcut(self):
        provider = OpenAITextProvider(api_key=FAKE_KEY)
        with patch.object(provider, "_client", return_value=self._fake_openai("TITULO")):
            self.assertEqual(
                provider.complete_text(system="s", user="u", model="m"), "TITULO"
            )


class TestAiTitlePhase4(_EnvIsolated):
    """Comportamento tem que ser IDÊNTICO ao de antes da refatoração."""

    def test_returns_none_without_ai(self):
        os.environ["CLIPRADAR_MODE"] = "mock"
        self.assertIsNone(ai_title.generate_ai_title("qualquer texto"))

    def test_returns_none_with_empty_excerpt(self):
        self._enable_ai()
        self.assertIsNone(ai_title.generate_ai_title(""))

    def test_title_is_uppercased_and_unquoted(self):
        self._enable_ai()
        fake = MagicMock()
        fake.complete_text.return_value = '  "clutch insano"  '
        with patch("core.ai_title.get_provider", return_value=fake):
            self.assertEqual(ai_title.generate_ai_title("texto"), "CLUTCH INSANO")

    def test_provider_failure_returns_none(self):
        self._enable_ai()
        fake = MagicMock()
        fake.complete_text.return_value = None
        with patch("core.ai_title.get_provider", return_value=fake):
            self.assertIsNone(ai_title.generate_ai_title("texto"))

    def test_old_signature_with_api_key_still_accepted(self):
        """thumbnail.py chama com api_key= — não pode quebrar."""
        os.environ["CLIPRADAR_MODE"] = "mock"
        self.assertIsNone(
            ai_title.generate_ai_title("texto", api_key="sk-algo", model="gpt-4o-mini")
        )


class TestEditPlanPhase4(_EnvIsolated):
    MOMENT = {
        "start_seconds": 100.0,
        "end_seconds": 130.0,
        "context_start_seconds": 95.0,
        "transcript_excerpt": "não acredito que peguei esse round",
        "breakdown": {"gameplay_intensity": 80, "emotional_reaction": 90},
    }

    def test_returns_none_without_ai(self):
        os.environ["CLIPRADAR_MODE"] = "mock"
        self.assertIsNone(edit_plan.generate_edit_plan(self.MOMENT))

    def test_all_plan_fields_preserved(self):
        """Os campos do Edit Plan não podem ter se perdido na refatoração."""
        self._enable_ai()
        plan_json = (
            '{"clip_type": "clutch", "hook_point": 98, "payoff_point": 115, '
            '"exit_point": 128, "recommended_subtitle_style": "bold_yellow", '
            '"zoom_events": [{"start": 112, "end": 118}], '
            '"highlight_words": ["clutch", "round"], '
            '"silence_cut_safe": false, "explanation": "Momento de virada."}'
        )
        fake = MagicMock()
        fake.complete_text.return_value = plan_json
        with patch("core.edit_plan.get_provider", return_value=fake):
            plan = edit_plan.generate_edit_plan(self.MOMENT)

        self.assertIsNotNone(plan)
        for field in ("clip_type", "hook_point", "payoff_point", "exit_point",
                      "recommended_subtitle_style", "zoom_events",
                      "highlight_words", "silence_cut_safe", "explanation"):
            self.assertIn(field, plan, f"campo '{field}' sumiu do Edit Plan")
        self.assertEqual(plan["clip_type"], "clutch")
        self.assertIs(plan["silence_cut_safe"], False)

    def test_uses_json_mode(self):
        self._enable_ai()
        fake = MagicMock()
        fake.complete_text.return_value = None
        with patch("core.edit_plan.get_provider", return_value=fake):
            edit_plan.generate_edit_plan(self.MOMENT)
        self.assertIs(fake.complete_text.call_args.kwargs["json_mode"], True)

    def test_malformed_json_returns_none(self):
        self._enable_ai()
        fake = MagicMock()
        fake.complete_text.return_value = "isso nao e json"
        with patch("core.edit_plan.get_provider", return_value=fake):
            self.assertIsNone(edit_plan.generate_edit_plan(self.MOMENT))

    def test_old_signature_still_accepted(self):
        """montage.py chama com (moment, api_key, model) posicionais."""
        os.environ["CLIPRADAR_MODE"] = "mock"
        self.assertIsNone(
            edit_plan.generate_edit_plan(self.MOMENT, "sk-algo", "gpt-4o-mini")
        )


class TestNoDirectOpenAICalls(unittest.TestCase):
    """
    A regra central da Fase 3: ninguém fala com a OpenAI direto.
    Só o openai_provider.py pode importar a biblioteca.
    """

    def test_only_provider_imports_openai(self):
        from pathlib import Path
        offenders = []
        for path in Path("core").rglob("*.py"):
            if path.name == "openai_provider.py":
                continue
            if "from openai import" in path.read_text(encoding="utf-8"):
                offenders.append(str(path))
        self.assertEqual(offenders, [], f"ainda chamam a OpenAI direto: {offenders}")


if __name__ == "__main__":
    unittest.main()
