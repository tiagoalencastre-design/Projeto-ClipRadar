"""
Testes da contabilização real da cota.

O PROBLEMA ORIGINAL: `UsageRepository.record()` só era chamado nos testes.
No fluxo real, nada gravava consumo — `minutes_used` ficava sempre em zero e
os limites de 90/400/1200 minutos nunca vinculavam.

Estes testes cobrem as quatro situações que quebram um contador de cota:
retry, job duplicado, requisições simultâneas e processamento interrompido.
"""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from core import database, persistence
from core.plans import FREE, get_plan
from core.repositories import UsageRepository

API_SOURCE = Path("core/api_server.py").read_text(encoding="utf-8")


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

    def used(self) -> float:
        return UsageRepository.minutes_this_month(self.user_id)

    def job(self, job_id: str) -> str:
        """
        Cria o registro do job antes de reservar cota.

        Não é detalhe de teste: usage_events.job_id tem FOREIGN KEY para
        jobs(id), e o PRAGMA foreign_keys está ligado. No fluxo real, o job
        é registrado antes da reserva pela mesma razão.
        """
        from core.repositories import JobRepository
        JobRepository.create(job_id, self.user_id, "generate")
        return job_id


class TestUsageIsRecorded(_TempDatabase):
    def test_reservation_counts_towards_the_quota(self):
        """Antes, processar não movia o contador."""
        self.assertEqual(self.used(), 0.0)
        persistence.reserve_usage(self.user_id, self.job("job-1"), 45.0)
        self.assertAlmostEqual(self.used(), 45.0)

    def test_multiple_jobs_accumulate(self):
        persistence.reserve_usage(self.user_id, self.job("job-1"), 30.0)
        persistence.reserve_usage(self.user_id, self.job("job-2"), 25.5)
        self.assertAlmostEqual(self.used(), 55.5)

    def test_zero_or_negative_minutes_are_ignored(self):
        """Duração ilegível não pode cobrar nada."""
        self.assertFalse(persistence.reserve_usage(self.user_id, self.job("job-x"), 0.0))
        self.assertFalse(persistence.reserve_usage(self.user_id, self.job("job-y"), -5.0))
        self.assertEqual(self.used(), 0.0)


class TestRetryAndDuplicates(_TempDatabase):
    def test_same_job_reserved_twice_charges_once(self):
        """Retry ou clique duplo não pode cobrar em dobro."""
        first = persistence.reserve_usage(self.user_id, self.job("job-1"), 40.0)
        second = persistence.reserve_usage(self.user_id, self.job("job-1"), 40.0)
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertAlmostEqual(self.used(), 40.0)

    def test_different_jobs_are_independent(self):
        persistence.reserve_usage(self.user_id, self.job("job-1"), 40.0)
        persistence.reserve_usage(self.user_id, self.job("job-2"), 40.0)
        self.assertAlmostEqual(self.used(), 80.0)


class TestConcurrency(_TempDatabase):
    def test_parallel_reservations_of_the_same_job_charge_once(self):
        """
        Duas requisições simultâneas com o mesmo job_id. O índice único no
        banco é quem garante que só uma passa.
        """
        results: list[bool] = []
        barrier = threading.Barrier(8)

        def reserve():
            barrier.wait()
            results.append(persistence.reserve_usage(self.user_id, self.job("job-race"), 10.0))

        threads = [threading.Thread(target=reserve) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sum(results), 1, "mais de uma reserva passou")
        self.assertAlmostEqual(self.used(), 10.0)

    def test_quota_check_and_reservation_share_a_lock(self):
        """
        Sem serializar os dois passos, dois envios leem a mesma cota livre,
        ambos passam, e o usuário processa o dobro do plano.
        """
        self.assertIn("_quota_lock = threading.Lock()", API_SOURCE)
        section = API_SOURCE[API_SOURCE.index("def _enforce_quota"):]
        section = section[:section.index("def _usage_status")]
        self.assertIn("with _quota_lock:", section)
        self.assertIn("can_process(minutes)", section)
        self.assertIn("reserve_usage", section)


class TestRefund(_TempDatabase):
    def test_failed_job_gives_the_quota_back(self):
        """Erro de FFmpeg no primeiro segundo não pode consumir a hora."""
        persistence.reserve_usage(self.user_id, self.job("job-1"), 60.0)
        self.assertAlmostEqual(self.used(), 60.0)
        self.assertTrue(persistence.refund_usage("job-1"))
        self.assertEqual(self.used(), 0.0)

    def test_refund_of_unknown_job_is_harmless(self):
        self.assertFalse(persistence.refund_usage("nao-existe"))

    def test_refund_only_touches_its_own_job(self):
        persistence.reserve_usage(self.user_id, self.job("job-1"), 30.0)
        persistence.reserve_usage(self.user_id, self.job("job-2"), 20.0)
        persistence.refund_usage("job-1")
        self.assertAlmostEqual(self.used(), 20.0)

    def test_job_can_be_reserved_again_after_refund(self):
        persistence.reserve_usage(self.user_id, self.job("job-1"), 30.0)
        persistence.refund_usage("job-1")
        self.assertTrue(persistence.reserve_usage(self.user_id, self.job("job-1"), 30.0))


class TestRefundIsWiredIntoTheFlow(unittest.TestCase):
    def test_refund_on_pipeline_error(self):
        self.assertIn("persistence.refund_usage(job_id)", API_SOURCE)

    def test_slot_is_acquired_before_the_reservation(self):
        """
        A vaga da fila é pedida ANTES de reservar cota. Assim, uma recusa
        por fila cheia não chega a cobrar nada — não há o que estornar.
        """
        section = API_SOURCE[API_SOURCE.index("def generate("):]
        section = section[:section.index("queue.submit(")]
        self.assertLess(
            section.index("has_capacity"),
            section.index("_enforce_quota"),
            "a cota está sendo reservada antes de checar a vaga",
        )

    def test_job_row_exists_before_the_reservation(self):
        """
        usage_events.job_id tem FOREIGN KEY para jobs(id). Reservar antes de
        registrar o job falha silenciosamente e o consumo não é contabilizado
        — foi exatamente o que aconteceu ao ligar o PRAGMA foreign_keys.
        """
        section = API_SOURCE[API_SOURCE.index("def generate("):]
        section = section[:section.index("queue.submit(")]
        self.assertLess(
            section.index("jobs[job_id] = {"),
            section.index("_enforce_quota"),
            "a reserva acontece antes do registro do job",
        )

    def test_quota_failure_does_not_occupy_a_slot(self):
        """
        A vaga só é ocupada no submit à fila. Como a cota é verificada
        ANTES do envio, uma recusa por cota não deixa vaga presa — não há
        o que liberar.
        """
        section = API_SOURCE[API_SOURCE.index("def generate("):]
        section = section[:section.index("queue.submit(")]
        self.assertIn("_enforce_quota", section)
        self.assertNotIn("_release_job_slot", API_SOURCE)

    def test_every_error_branch_refunds(self):
        """Quatro ramos de erro: erro tratado e inesperado, em generate e analyze."""
        self.assertGreaterEqual(API_SOURCE.count("persistence.refund_usage(job_id)"), 4)


class TestQuotaActuallyBinds(_TempDatabase):
    def test_free_plan_blocks_after_the_limit(self):
        """O teste que o sistema antigo não passaria: o limite vincula."""
        from core.plans import UsageStatus

        limit = get_plan(FREE).monthly_minutes
        persistence.reserve_usage(self.user_id, self.job("job-1"), limit - 5)

        status = UsageStatus(get_plan(FREE), minutes_used=self.used())
        self.assertFalse(status.can_process(30)[0])
        self.assertTrue(status.can_process(4)[0])


if __name__ == "__main__":
    unittest.main()
