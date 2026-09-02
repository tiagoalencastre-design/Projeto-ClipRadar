"""
Testes do PersistentJobStore — Fase 2b.

Prova duas coisas:
  1. Ele se comporta EXATAMENTE como um dicionário comum (nada quebra).
  2. Ele grava no banco automaticamente (o problema que a Fase 2 resolve).
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import database
from core.job_store import PersistentJobStore
from core.repositories import JobRepository


class _TempDatabase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._patcher = patch.object(
            database, "DB_PATH", Path(self._tmpdir.name) / "teste.db"
        )
        self._patcher.start()
        database.init_db()
        with database.get_db() as conn:
            cursor = conn.execute(
                """INSERT INTO users (email, username, password_hash, password_salt,
                   storage_key, email_verified, created_at)
                   VALUES ('t@e.com','gringo','h','s','k',1,'2026-01-01T00:00:00')"""
            )
            conn.commit()
            self.user_id = cursor.lastrowid

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()


class TestBehavesLikeDict(_TempDatabase):
    """Compatibilidade: o api_server.py não pode notar diferença."""

    def test_set_and_get(self):
        store = PersistentJobStore("generate")
        store["j1"] = {"status": "running", "user_id": self.user_id}
        self.assertEqual(store["j1"]["status"], "running")

    def test_contains_len_and_delete(self):
        store = PersistentJobStore("generate")
        store["j1"] = {"status": "running", "user_id": self.user_id}
        self.assertIn("j1", store)
        self.assertEqual(len(store), 1)
        del store["j1"]
        self.assertNotIn("j1", store)

    def test_keys_and_items_work(self):
        store = PersistentJobStore("generate")
        store["j1"] = {"status": "running", "user_id": self.user_id}
        self.assertEqual(list(store.keys()), ["j1"])
        self.assertEqual(len(list(store.items())), 1)

    def test_get_with_default(self):
        store = PersistentJobStore("generate")
        self.assertIsNone(store.get("nao-existe"))

    def test_non_persisted_fields_still_stored_in_memory(self):
        store = PersistentJobStore("generate")
        store["j1"] = {"status": "running", "user_id": self.user_id}
        store["j1"]["result"] = {"clips": 5}
        store["j1"]["created_at"] = 12345.6
        self.assertEqual(store["j1"]["result"], {"clips": 5})
        self.assertEqual(store["j1"]["created_at"], 12345.6)


class TestPersistsToDatabase(_TempDatabase):
    """O objetivo da fase: o histórico sobrevive ao restart."""

    def test_creating_job_writes_to_database(self):
        store = PersistentJobStore("generate")
        store["j1"] = {"status": "running", "user_id": self.user_id}
        job = JobRepository.get("j1")
        self.assertIsNotNone(job)
        self.assertEqual(job.job_type, "generate")
        self.assertEqual(job.user_id, self.user_id)

    def test_update_syncs_status_and_step(self):
        store = PersistentJobStore("generate")
        store["j1"] = {"status": "running", "user_id": self.user_id}
        store["j1"].update({"status": "done", "step": "finalizado"})
        job = JobRepository.get("j1")
        self.assertEqual(job.status, "done")
        self.assertEqual(job.step, "finalizado")
        self.assertTrue(job.is_finished)

    def test_direct_key_assignment_syncs(self):
        store = PersistentJobStore("analyze")
        store["j2"] = {"status": "running", "user_id": self.user_id}
        store["j2"]["step"] = "transcrevendo"
        self.assertEqual(JobRepository.get("j2").step, "transcrevendo")

    def test_error_is_persisted(self):
        store = PersistentJobStore("generate")
        store["j3"] = {"status": "running", "user_id": self.user_id}
        store["j3"].update({"status": "error", "error": "FFmpeg falhou"})
        job = JobRepository.get("j3")
        self.assertEqual(job.status, "error")
        self.assertEqual(job.error, "FFmpeg falhou")

    def test_job_type_recorded_per_store(self):
        PersistentJobStore("generate")["a"] = {"status": "running", "user_id": self.user_id}
        PersistentJobStore("analyze")["b"] = {"status": "running", "user_id": self.user_id}
        PersistentJobStore("youtube_download")["c"] = {"status": "running", "user_id": self.user_id}
        self.assertEqual(JobRepository.get("a").job_type, "generate")
        self.assertEqual(JobRepository.get("b").job_type, "analyze")
        self.assertEqual(JobRepository.get("c").job_type, "youtube_download")

    def test_history_survives_memory_cleanup(self):
        """A limpeza tira da RAM, mas o histórico fica no banco."""
        store = PersistentJobStore("generate")
        store["j4"] = {"status": "running", "user_id": self.user_id}
        store["j4"].update({"status": "done"})
        del store["j4"]
        self.assertNotIn("j4", store)
        self.assertIsNotNone(JobRepository.get("j4"))


class TestNeverBreaksTheApp(_TempDatabase):
    """Falha de banco não pode derrubar processamento nenhum."""

    def test_missing_user_id_does_not_crash(self):
        store = PersistentJobStore("generate")
        store["sem-dono"] = {"status": "running"}   # sem user_id
        self.assertEqual(store["sem-dono"]["status"], "running")
        self.assertIsNone(JobRepository.get("sem-dono"))

    def test_database_failure_does_not_crash(self):
        store = PersistentJobStore("generate")
        with patch.object(database, "get_db",
                          side_effect=sqlite3.OperationalError("travado")):
            store["j5"] = {"status": "running", "user_id": self.user_id}
            store["j5"].update({"status": "done"})
        # A memória continua correta mesmo com o banco fora do ar.
        self.assertEqual(store["j5"]["status"], "done")


if __name__ == "__main__":
    unittest.main()
