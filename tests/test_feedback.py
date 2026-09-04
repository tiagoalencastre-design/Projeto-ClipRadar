"""
Testes da captura de feedback dos criadores.

O objetivo do recurso: transformar cada uso em dado. Os botões de aprovar e
rejeitar já existiam, mas só mudavam a cor — a opinião se perdia.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import database
from core.repositories import REJECTION_REASONS, FeedbackRepository

HTML = Path("web/index.html").read_text(encoding="utf-8")
API = Path("core/api_server.py").read_text(encoding="utf-8")


class _TempDatabase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patcher = patch.object(database, "DB_PATH", Path(self._tmp.name) / "t.db")
        self._patcher.start()
        database.init_db()
        with database.get_db() as conn:
            cur = conn.execute(
                """INSERT INTO users (email, username, password_hash, password_salt,
                   storage_key, email_verified, created_at)
                   VALUES ('t@e.com','g','h','s','k',1,'2026-01-01T00:00:00')"""
            )
            conn.commit()
            self.user_id = cur.lastrowid

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()


class TestFeedbackStorage(_TempDatabase):
    def test_approval_is_recorded(self):
        self.assertIsInstance(
            FeedbackRepository.record(self.user_id, "approved", clip_identifier="C1"), int
        )
        self.assertEqual(FeedbackRepository.summary(self.user_id)["approved"], 1)

    def test_rejection_with_reason(self):
        FeedbackRepository.record(
            self.user_id, "rejected", clip_identifier="C1", reason="bad_start")
        summary = FeedbackRepository.summary(self.user_id)
        self.assertEqual(summary["rejected"], 1)
        self.assertEqual(summary["rejection_reasons"]["bad_start"], 1)

    def test_changing_your_mind_replaces_the_vote(self):
        """Senão a contagem infla e a taxa de aprovação mente."""
        FeedbackRepository.record(self.user_id, "rejected", clip_identifier="C1")
        FeedbackRepository.record(self.user_id, "approved", clip_identifier="C1")
        summary = FeedbackRepository.summary(self.user_id)
        self.assertEqual(summary["total"], 1)
        self.assertEqual(summary["approved"], 1)

    def test_approval_rate_is_the_headline_metric(self):
        for i in range(3):
            FeedbackRepository.record(self.user_id, "approved", clip_identifier=f"A{i}")
        for i in range(7):
            FeedbackRepository.record(self.user_id, "rejected", clip_identifier=f"R{i}")
        self.assertAlmostEqual(
            FeedbackRepository.summary(self.user_id)["approval_rate"], 0.3, places=2)

    def test_signals_are_stored_for_later_comparison(self):
        """Guardar o que o sistema achou permite ajustar os pesos depois."""
        FeedbackRepository.record(
            self.user_id, "rejected", clip_identifier="C1",
            signals=json.dumps({"hook": 90, "standalone": 30}),
        )
        stored = FeedbackRepository.list_for_user(self.user_id)[0]
        self.assertEqual(json.loads(stored.signals)["standalone"], 30)

    def test_empty_summary_does_not_crash(self):
        summary = FeedbackRepository.summary(self.user_id)
        self.assertEqual(summary["total"], 0)
        self.assertIsNone(summary["approval_rate"])

    def test_database_failure_never_breaks_the_flow(self):
        with patch.object(database, "get_db",
                          side_effect=sqlite3.OperationalError("travado")):
            self.assertIsNone(FeedbackRepository.record(self.user_id, "approved"))
            self.assertEqual(FeedbackRepository.summary(self.user_id)["total"], 0)


class TestRejectionReasons(unittest.TestCase):
    def test_reasons_are_a_closed_list(self):
        """Texto livre quase ninguém preenche, e não dá pra agregar."""
        self.assertGreaterEqual(len(REJECTION_REASONS), 6)

    def test_each_reason_points_to_a_part_of_the_system(self):
        for key in ("bad_start", "bad_end", "no_context", "bad_framing",
                    "bad_captions", "duplicate", "boring"):
            self.assertIn(key, REJECTION_REASONS)

    def test_api_rejects_unknown_reason(self):
        self.assertIn("Motivo inválido", API)


class TestEndpoints(unittest.TestCase):
    def test_feedback_endpoint_exists(self):
        self.assertIn('@app.post("/api/clips/feedback")', API)

    def test_summary_endpoint_exists(self):
        self.assertIn('@app.get("/api/clips/feedback/summary")', API)

    def test_requires_login(self):
        section = API[API.index('@app.post("/api/clips/feedback")'):]
        self.assertIn("Depends(get_current_user)", section[:600])


class TestFrontend(unittest.TestCase):
    def test_buttons_now_send_the_vote(self):
        """Antes só mudavam a cor."""
        self.assertIn("sendClipFeedback(clip, 'approved')", HTML)
        self.assertIn("sendClipFeedback(clip, 'rejected')", HTML)

    def test_reason_prompt_exists(self):
        self.assertIn("askRejectionReason", HTML)

    def test_reason_prompt_is_one_click_only(self):
        """Nada de campo de texto: reduz a chance de a pessoa ignorar."""
        prompt = HTML[HTML.index("function askRejectionReason"):]
        prompt = prompt[:prompt.index("function selectClip")]
        self.assertNotIn("<input", prompt)
        self.assertNotIn("<textarea", prompt)

    def test_reason_prompt_disappears_on_its_own(self):
        """Não pode virar obstáculo pra quem só quer continuar usando."""
        self.assertIn("setTimeout(() => box.remove()", HTML)

    def test_failure_is_silent(self):
        """Feedback é útil, não crítico: erro de rede não pode atrapalhar."""
        fn = HTML[HTML.index("async function sendClipFeedback"):]
        self.assertIn("catch (e) { /* silencioso de propósito */ }", fn[:1200])

    def test_job_id_is_tracked(self):
        self.assertIn("let currentJobId = null;", HTML)
        self.assertIn("currentJobId = jobId;", HTML)

    def test_reasons_translated_in_every_language(self):
        self.assertEqual(HTML.count("reason_question:"), 3)
        self.assertEqual(HTML.count("reason_bad_start:"), 3)


if __name__ == "__main__":
    unittest.main()
