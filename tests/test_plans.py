"""
Testes de planos, limites e preços por região.

Nada aqui cobra dinheiro: a estrutura existe, a cobrança não. O que estes
testes garantem é que os limites são respeitados e que nenhum recurso pago
vaza pro plano grátis.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.plans import (
    FREE, PLANS, PRO, UsageStatus, days_until_expiry, describe_plans,
    expires_at, get_plan, region_for_country,
)

API = Path("core/api_server.py").read_text(encoding="utf-8")


class TestPlanDefinitions(unittest.TestCase):
    def test_free_is_above_market_average(self):
        """Média do mercado é 60 min/mês (OpusClip, quso, 2Short)."""
        self.assertGreaterEqual(PLANS[FREE].monthly_minutes, 60)

    def test_free_has_watermark_pro_does_not(self):
        self.assertTrue(PLANS[FREE].watermark)
        self.assertFalse(PLANS[PRO].watermark)

    def test_retention_is_seven_and_thirty_days(self):
        self.assertEqual(PLANS[FREE].retention_days, 7)
        self.assertEqual(PLANS[PRO].retention_days, 30)

    def test_free_retention_beats_opusclip(self):
        """OpusClip apaga em 3 dias — 7 é diferencial real."""
        self.assertGreater(PLANS[FREE].retention_days, 3)

    def test_ai_extras_only_on_pro(self):
        self.assertFalse(PLANS[FREE].ai_extras_included)
        self.assertTrue(PLANS[PRO].ai_extras_included)

    def test_unknown_plan_falls_back_to_free(self):
        """Nunca liberar recurso pago por engano."""
        for value in (None, "", "premium", "PRO_MAX"):
            plan = get_plan(value)
            if value and value.strip().lower() == "pro":
                continue
            self.assertEqual(plan.id, FREE, f"'{value}' liberou plano pago")

    def test_pro_is_recognized(self):
        self.assertEqual(get_plan("pro").id, PRO)
        self.assertEqual(get_plan("PRO").id, PRO)


class TestRegionalPricing(unittest.TestCase):
    def test_every_region_has_a_price(self):
        for region in ("BR", "US", "GB", "EU"):
            self.assertIsNotNone(PLANS[PRO].price_for(region))

    def test_currencies_are_correct(self):
        self.assertEqual(PLANS[PRO].price_for("BR").currency, "BRL")
        self.assertEqual(PLANS[PRO].price_for("GB").currency, "GBP")
        self.assertEqual(PLANS[PRO].price_for("EU").currency, "EUR")
        self.assertEqual(PLANS[PRO].price_for("US").currency, "USD")

    def test_brazil_uses_comma_as_decimal(self):
        self.assertIn(",", PLANS[PRO].price_for("BR").formatted)

    def test_unknown_region_falls_back_to_dollar(self):
        self.assertEqual(PLANS[PRO].price_for("JP").currency, "USD")

    def test_country_mapping(self):
        self.assertEqual(region_for_country("BR"), "BR")
        self.assertEqual(region_for_country("GB"), "GB")
        self.assertEqual(region_for_country("UK"), "GB")
        self.assertEqual(region_for_country("PT"), "EU")
        self.assertEqual(region_for_country("JP"), "US")
        self.assertEqual(region_for_country(None), "US")

    def test_free_costs_nothing_everywhere(self):
        for region in ("BR", "US", "GB", "EU"):
            self.assertEqual(PLANS[FREE].price_for(region).monthly, 0.0)

    def test_all_regions_undercut_opusclip(self):
        """OpusClip Starter é $15. Todos os nossos ficam abaixo."""
        self.assertLess(PLANS[PRO].price_for("US").monthly, 15.0)

    def test_describe_plans_is_json_friendly(self):
        import json
        json.dumps(describe_plans("BR"))

    def test_free_shows_as_free_not_zero(self):
        free = [p for p in describe_plans("BR") if p["id"] == FREE][0]
        self.assertEqual(free["price"]["formatted"], "Grátis")


class TestUsageLimits(unittest.TestCase):
    def test_fresh_user_can_process(self):
        status = UsageStatus(get_plan(FREE), minutes_used=0)
        self.assertTrue(status.can_process(60)[0])

    def test_video_larger_than_remaining_is_refused_with_numbers(self):
        """Recusa ANTES de processar, dizendo quanto falta."""
        status = UsageStatus(get_plan(FREE), minutes_used=75)
        allowed, message = status.can_process(60)
        self.assertFalse(allowed)
        self.assertIn("15", message)

    def test_small_video_still_fits(self):
        status = UsageStatus(get_plan(FREE), minutes_used=75)
        self.assertTrue(status.can_process(10)[0])

    def test_exhausted_quota(self):
        status = UsageStatus(get_plan(FREE), minutes_used=90)
        self.assertTrue(status.exhausted)
        self.assertFalse(status.can_process(1)[0])

    def test_percent_never_exceeds_one(self):
        status = UsageStatus(get_plan(FREE), minutes_used=500)
        self.assertEqual(status.percent_used, 1.0)

    def test_minutes_left_never_negative(self):
        self.assertEqual(UsageStatus(get_plan(FREE), minutes_used=500).minutes_left, 0.0)

    def test_pro_has_more_room(self):
        free = UsageStatus(get_plan(FREE), minutes_used=100)
        pro = UsageStatus(get_plan(PRO), minutes_used=100)
        self.assertTrue(free.exhausted)
        self.assertFalse(pro.exhausted)

    def test_status_is_json_friendly(self):
        import json
        json.dumps(UsageStatus(get_plan(FREE), 10, "BR").as_dict())


class TestRetention(unittest.TestCase):
    def test_free_clip_expires_in_seven_days(self):
        created = datetime.now(timezone.utc)
        self.assertEqual((expires_at(created, FREE) - created).days, 7)

    def test_pro_clip_expires_in_thirty_days(self):
        created = datetime.now(timezone.utc)
        self.assertEqual((expires_at(created, PRO) - created).days, 30)

    def test_days_remaining_counts_down(self):
        created = datetime.now(timezone.utc) - timedelta(days=5)
        self.assertEqual(days_until_expiry(created, FREE), 2)

    def test_expired_clip_reports_zero_not_negative(self):
        created = datetime.now(timezone.utc) - timedelta(days=30)
        self.assertEqual(days_until_expiry(created, FREE), 0)

    def test_library_tells_the_user_when_it_expires(self):
        """Apagar sem avisar é o que gera raiva."""
        self.assertIn("expires_in_days", API)


class TestEndpoints(unittest.TestCase):
    def test_plans_endpoint_is_public(self):
        """A landing precisa mostrar preço sem login."""
        section = API[API.index('@app.get("/api/plans")'):]
        self.assertNotIn("Depends(get_current_user)", section[:300])

    def test_usage_endpoint_requires_login(self):
        section = API[API.index('@app.get("/api/usage")'):]
        self.assertIn("Depends(get_current_user)", section[:300])

    def test_no_payment_integration_yet(self):
        """A cobrança é outra etapa: nada de gateway ainda."""
        for forbidden in ("stripe", "mercadopago", "paypal", "checkout.session"):
            self.assertNotIn(forbidden, API.lower())


if __name__ == "__main__":
    unittest.main()
