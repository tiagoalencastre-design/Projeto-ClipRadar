"""
Testes da tela de preços, do aviso de expiração e do agendamento da limpeza.
"""
from __future__ import annotations

import unittest
from pathlib import Path

def _frontend_sources() -> str:
    """
    HTML + CSS + JS do painel, concatenados.

    O web/index.html tinha 1.828 linhas com os três juntos. Depois da
    separação, o CSS vive em web/assets/app.css e o JS em app.js — mas as
    asserções destes testes continuam valendo sobre o conjunto, que é o que
    o navegador de fato carrega.
    """
    return "\n".join(
        Path(p).read_text(encoding="utf-8")
        for p in ("web/index.html", "web/assets/app.css", "web/assets/app.js")
    )


LANDING = Path("web/landing.html").read_text(encoding="utf-8")
APP = _frontend_sources()
API = Path("core/api_server.py").read_text(encoding="utf-8")
RETENTION = Path("core/retention.py").read_text(encoding="utf-8")


class TestPricingPage(unittest.TestCase):
    def test_landing_has_a_pricing_grid(self):
        self.assertIn('id="pricingGrid"', LANDING)

    def test_prices_come_from_the_api_not_hardcoded(self):
        """Mudar o preço não pode exigir editar HTML."""
        self.assertIn("fetch('/api/plans?country=", LANDING)
        for hardcoded in ("10.99", "13.99", "49,90", "12.99"):
            self.assertNotIn(hardcoded, LANDING)

    def test_region_detected_without_asking_permission(self):
        """Fuso horário do navegador: sem pedir localização, sem serviço externo."""
        self.assertIn("Intl.DateTimeFormat().resolvedOptions().timeZone", LANDING)
        self.assertNotIn("navigator.geolocation", LANDING)

    def test_brazilian_timezones_map_to_brazil(self):
        for zone in ("America/Sao_Paulo", "America/Fortaleza", "America/Manaus"):
            self.assertIn(zone, LANDING)

    def test_failure_shows_a_message_not_a_blank_section(self):
        self.assertIn("Não foi possível carregar os planos", LANDING)


class TestExpiryWarning(unittest.TestCase):
    def test_badge_function_exists(self):
        self.assertIn("function expiryBadge", APP)

    def test_library_shows_the_badge(self):
        self.assertIn("${expiryBadge(c.expires_in_days)}", APP)

    def test_urgent_when_two_days_or_less(self):
        self.assertIn("const soon = days <= 2;", APP)

    def test_translated_in_every_language(self):
        self.assertEqual(APP.count("expires_today:"), 3)
        self.assertEqual(APP.count("expires_in:"), 3)

    def test_backend_provides_the_field(self):
        self.assertIn("expires_in_days", API)


class TestUsageDisplay(unittest.TestCase):
    def test_usage_is_loaded(self):
        self.assertIn("fetch('/api/usage')", APP)

    def test_shows_minutes_left_not_only_used(self):
        """O que importa pro usuário é quanto AINDA dá pra processar."""
        self.assertIn("u.minutes_left", APP)

    def test_failure_is_silent(self):
        fn = APP[APP.index("async function loadUsage"):]
        self.assertIn("catch (e) { /* silencioso", fn[:900])


class TestCleanupScheduler(unittest.TestCase):
    def test_scheduler_exists(self):
        self.assertIn("def start_scheduler", RETENTION)

    def test_started_on_boot(self):
        self.assertIn("retention.start_scheduler(CLIPS_DIR)", API)

    def test_runs_as_daemon(self):
        """Não pode impedir o servidor de encerrar."""
        self.assertIn("daemon=True", RETENTION)

    def test_does_not_delay_startup(self):
        """Primeira execução após 5 minutos, não no boot."""
        self.assertIn("time.sleep(300)", RETENTION)

    def test_survives_its_own_errors(self):
        """Limpeza que morre silenciosamente é pior que nenhuma limpeza."""
        loop = RETENTION[RETENTION.index("def _loop"):]
        self.assertIn("except Exception as e:", loop)

    def test_respects_each_user_plan(self):
        self.assertIn("plans_by_key.get(folder.name", RETENTION)

    def test_unknown_folder_uses_the_shortest_retention(self):
        self.assertIn('plans_by_key.get(folder.name, "free")', RETENTION)


if __name__ == "__main__":
    unittest.main()
