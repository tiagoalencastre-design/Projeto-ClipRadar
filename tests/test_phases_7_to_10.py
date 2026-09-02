"""
Testes das Fases 7 (fila), 8 (observabilidade), 9 (MCP) e 10 (produção).

O tema comum das quatro: nada de produção pode ligar sozinho. Cada fase
cria a estrutura e a deixa DESLIGADA até uma decisão explícita.
"""
from __future__ import annotations

import io
import json
import os
import threading
import time
import unittest
import unittest.mock
from contextlib import redirect_stdout

from core import observability, queue as job_queue
from core.mcp import MCP_TOOLS, describe_tools, is_mcp_enabled
from core.observability import StageTimer, estimate_cost, log_event
from core.queue import JobQueue, ThreadQueue, get_queue, reset_queue


class _EnvIsolated(unittest.TestCase):
    ENV = ("CLIPRADAR_MODE",)

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in self.ENV}
        reset_queue()

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        reset_queue()


# ============================================================
# FASE 7 — fila
# ============================================================

class TestThreadQueue(_EnvIsolated):
    def test_runs_the_work(self):
        done = threading.Event()
        q = ThreadQueue(max_workers=2)
        self.assertTrue(q.submit(done.set))
        self.assertTrue(done.wait(timeout=3), "o job não rodou")

    def test_passes_arguments(self):
        result = []
        q = ThreadQueue(max_workers=2)
        q.submit(lambda a, b: result.append(a + b), 2, b=3)
        time.sleep(0.3)
        self.assertEqual(result, [5])

    def test_rejects_when_full(self):
        block = threading.Event()
        q = ThreadQueue(max_workers=1)
        self.assertTrue(q.submit(block.wait))
        self.assertFalse(q.has_capacity())
        self.assertFalse(q.submit(lambda: None), "aceitou job além do limite")
        block.set()

    def test_slot_released_even_when_job_crashes(self):
        """Se o release falhasse, a fila entupiria e o usuário não geraria mais nada."""
        def explode():
            raise RuntimeError("falha proposital")

        q = ThreadQueue(max_workers=1)
        q.submit(explode)
        time.sleep(0.4)
        self.assertEqual(q.active_count(), 0)
        self.assertTrue(q.has_capacity())

    def test_get_queue_is_shared(self):
        self.assertIs(get_queue(), get_queue())

    def test_default_backend_is_thread(self):
        self.assertIsInstance(get_queue(), ThreadQueue)
        self.assertIsInstance(get_queue(), JobQueue)


# ============================================================
# FASE 8 — observabilidade
# ============================================================

class TestLogging(_EnvIsolated):
    def test_readable_format_by_default(self):
        """Sem ligar nada, a saída continua legível como antes."""
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            log_event("transcricao", duration_seconds=12.345)
        output = buffer.getvalue()
        self.assertIn("[ClipRadar]", output)
        self.assertIn("transcricao", output)

    def test_all_required_fields_supported(self):
        event = log_event(
            stage="montagem", status="ok", job_id="j1", video_id=7,
            duration_seconds=30.0, model="gpt-4o-mini", provider="openai",
            estimated_cost_usd=0.0004,
        )
        for field in ("job_id", "video_id", "stage", "duration_seconds",
                      "model", "provider", "estimated_cost_usd", "status"):
            self.assertIn(field, event, f"campo '{field}' faltando")

    def test_structured_mode_emits_valid_json(self):
        buffer = io.StringIO()
        with unittest.mock.patch.object(
            observability, "get_app_config"
        ) as fake_config:
            fake_config.return_value.observability.structured = True
            with redirect_stdout(buffer):
                log_event("teste", job_id="j1")
        json.loads(buffer.getvalue().strip())  # não pode levantar exceção

    def test_none_fields_are_omitted(self):
        event = log_event("teste")
        self.assertNotIn("error", event)
        self.assertNotIn("model", event)


class TestStageTimer(_EnvIsolated):
    def test_measures_duration(self):
        with redirect_stdout(io.StringIO()):
            with StageTimer("etapa") as timer:
                time.sleep(0.15)
        self.assertGreaterEqual(timer.event["duration_seconds"], 0.1)

    def test_records_error_and_reraises(self):
        """Observar não pode engolir exceção — o erro tem que continuar subindo."""
        timer = StageTimer("etapa_que_falha")
        with redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):
                with timer:
                    raise ValueError("deu ruim")
        self.assertEqual(timer.event["status"], "error")
        self.assertIn("deu ruim", timer.event["error"])


class TestCostEstimate(unittest.TestCase):
    def test_known_model_returns_number(self):
        cost = estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
        self.assertAlmostEqual(cost, 0.75, places=4)

    def test_unknown_model_returns_none(self):
        """Melhor não ter número do que ter um número errado."""
        self.assertIsNone(estimate_cost("modelo-desconhecido", 1000, 1000))

    def test_zero_tokens_costs_nothing(self):
        self.assertEqual(estimate_cost("gpt-4o-mini", 0, 0), 0.0)


# ============================================================
# FASE 9 — MCP
# ============================================================

class TestMCPStaysOff(_EnvIsolated):
    def test_disabled_in_every_mode(self):
        for mode in ("development", "mock", "production"):
            os.environ["CLIPRADAR_MODE"] = mode
            self.assertFalse(is_mcp_enabled(), f"MCP ligou no modo {mode}")

    def test_tools_are_described_not_executed(self):
        """Nenhuma ferramenta tem código executável — é só catálogo."""
        for tool in MCP_TOOLS:
            self.assertFalse(hasattr(tool, "execute"))
            self.assertFalse(hasattr(tool, "run"))

    def test_read_only_flag_present_on_all(self):
        for tool in describe_tools():
            self.assertIn("read_only", tool)

    def test_write_tools_are_marked(self):
        """Ferramentas que gastam processamento não podem passar por leitura."""
        by_name = {t.name: t for t in MCP_TOOLS}
        self.assertFalse(by_name["generate_clips"].read_only)
        self.assertFalse(by_name["render_clip"].read_only)
        self.assertTrue(by_name["list_videos"].read_only)


# ============================================================
# FASE 10 — nada de produção liga sozinho
# ============================================================

class TestNothingActivatesItself(_EnvIsolated):
    def test_all_future_features_off_in_every_mode(self):
        from core.app_config import get_app_config
        for mode in ("development", "mock", "production", "test"):
            os.environ["CLIPRADAR_MODE"] = mode
            flags = get_app_config().flags
            self.assertFalse(flags.mcp_enabled, mode)
            self.assertFalse(flags.payments_enabled, mode)
            self.assertFalse(flags.credits_enabled, mode)
            self.assertFalse(flags.cloud_storage_enabled, mode)
            self.assertFalse(flags.distributed_queue_enabled, mode)
            self.assertFalse(flags.structured_logging_enabled, mode)

    def test_production_does_not_enable_extra_backends(self):
        from core.app_config import get_app_config
        os.environ["CLIPRADAR_MODE"] = "production"
        config = get_app_config()
        self.assertEqual(config.storage.backend, "local")
        self.assertEqual(config.queue.backend, "thread")
        self.assertFalse(config.observability.track_cost)


if __name__ == "__main__":
    import unittest.mock  # noqa: F401
    unittest.main()
