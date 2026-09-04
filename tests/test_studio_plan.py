"""
Testes do plano Studio: fila prioritária e Brand Kit.
"""
from __future__ import annotations

import threading
import unittest
from pathlib import Path

from core.plans import FREE, PLANS, PRO, STUDIO, get_plan
from core.queue import ThreadQueue

API = Path("core/api_server.py").read_text(encoding="utf-8")
LANDING = Path("web/landing.html").read_text(encoding="utf-8")


class TestStudioPlan(unittest.TestCase):
    def test_exists_with_three_tiers(self):
        self.assertEqual(len(PLANS), 3)
        self.assertIn(STUDIO, PLANS)

    def test_minutes_grow_across_tiers(self):
        self.assertLess(PLANS[FREE].monthly_minutes, PLANS[PRO].monthly_minutes)
        self.assertLess(PLANS[PRO].monthly_minutes, PLANS[STUDIO].monthly_minutes)

    def test_retention_grows_across_tiers(self):
        self.assertLess(PLANS[FREE].retention_days, PLANS[PRO].retention_days)
        self.assertLess(PLANS[PRO].retention_days, PLANS[STUDIO].retention_days)

    def test_price_grows_across_tiers(self):
        for region in ("BR", "US", "GB", "EU"):
            self.assertLess(
                PLANS[PRO].price_for(region).monthly,
                PLANS[STUDIO].price_for(region).monthly,
                f"Studio não é mais caro que Pro em {region}",
            )

    def test_exclusive_features_only_on_studio(self):
        for plan_id in (FREE, PRO):
            self.assertFalse(PLANS[plan_id].priority_queue, plan_id)
            self.assertFalse(PLANS[plan_id].brand_kit, plan_id)
        self.assertTrue(PLANS[STUDIO].priority_queue)
        self.assertTrue(PLANS[STUDIO].brand_kit)

    def test_studio_has_no_watermark(self):
        self.assertFalse(PLANS[STUDIO].watermark)

    def test_unknown_plan_never_grants_studio_features(self):
        plan = get_plan("studio_plus")
        self.assertFalse(plan.priority_queue)
        self.assertFalse(plan.brand_kit)


class TestPriorityQueue(unittest.TestCase):
    def test_priority_gets_an_extra_slot(self):
        """Assinante não pode ficar preso atrás de dois usuários grátis."""
        blocker = threading.Event()
        queue = ThreadQueue(max_workers=2, priority_slots=1)
        try:
            self.assertTrue(queue.submit(blocker.wait))
            self.assertTrue(queue.submit(blocker.wait))
            self.assertFalse(queue.submit(lambda: None))
            self.assertTrue(queue.submit(lambda: None, priority=True))
        finally:
            blocker.set()

    def test_priority_is_not_unlimited(self):
        """Cada vaga a mais é CPU disputada — o extra também tem teto."""
        blocker = threading.Event()
        queue = ThreadQueue(max_workers=1, priority_slots=1)
        try:
            self.assertTrue(queue.submit(blocker.wait, priority=True))
            self.assertTrue(queue.submit(blocker.wait, priority=True))
            self.assertFalse(queue.submit(lambda: None, priority=True))
        finally:
            blocker.set()

    def test_default_is_not_priority(self):
        blocker = threading.Event()
        queue = ThreadQueue(max_workers=1, priority_slots=1)
        try:
            queue.submit(blocker.wait)
            self.assertFalse(queue.has_capacity())
            self.assertTrue(queue.has_capacity(priority=True))
        finally:
            blocker.set()

    def test_server_uses_priority_for_studio(self):
        self.assertIn("_try_acquire_job_slot(priority=plan.priority_queue)", API)


class TestBrandKit(unittest.TestCase):
    def test_upload_endpoint_exists(self):
        self.assertIn('@app.post("/api/brand-kit")', API)

    def test_blocked_for_lower_plans(self):
        section = API[API.index('@app.post("/api/brand-kit")'):]
        self.assertIn("if not plan.brand_kit:", section[:900])
        self.assertIn("402", section[:1100])

    def test_converts_to_transparent_png(self):
        """FFmpeg precisa de canal alfa pra sobrepor sem fundo quadrado."""
        self.assertIn('image.convert("RGBA")', API)

    def test_limits_file_size_and_dimensions(self):
        self.assertIn("MAX_LOGO_BYTES", API)
        self.assertIn("image.thumbnail((1000, 1000))", API)

    def test_logo_replaces_the_cliradar_mark(self):
        from core.montage import build_watermark_filter, VERTICAL_RES
        custom = build_watermark_filter(VERTICAL_RES, image_path="web/assets/watermark.png")
        self.assertIsNotNone(custom)

    def test_missing_logo_falls_back_without_crashing(self):
        from core.montage import build_watermark_filter, VERTICAL_RES
        self.assertIsNone(
            build_watermark_filter(VERTICAL_RES, image_path="/nao/existe.png")
        )

    def test_render_functions_accept_the_logo(self):
        import inspect
        from core.montage import export_separate_clips, render_single_clip, run_montage
        for fn in (run_montage, export_separate_clips, render_single_clip):
            self.assertIn("watermark_path", inspect.signature(fn).parameters, fn.__name__)


class TestPricingPageShowsThree(unittest.TestCase):
    def test_studio_features_rendered(self):
        self.assertIn("p.priority_queue", LANDING)
        self.assertIn("p.brand_kit", LANDING)

    def test_pro_is_highlighted_as_the_middle_choice(self):
        self.assertIn("Mais escolhido", LANDING)

    def test_paid_plans_say_subscribe(self):
        self.assertIn("const paid = pro || studio;", LANDING)


if __name__ == "__main__":
    unittest.main()
