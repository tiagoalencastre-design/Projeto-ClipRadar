"""
Testes do core/database.py — Fase 2 (tabelas de domínio).

Roda com:
    python -m unittest tests.test_database -v

Usa um arquivo de banco TEMPORÁRIO (nunca toca no data/cliparadar.db real).
"""
from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path


class TestDatabasePhase2(unittest.TestCase):
    def setUp(self):
        # Cada teste usa seu PRÓPRIO arquivo de banco temporário — isolado,
        # e nunca é o banco de verdade do usuário.
        self._tmp_dir = tempfile.mkdtemp()
        self._db_path = Path(self._tmp_dir) / "test.db"

        import core.database as database
        importlib.reload(database)
        database.DB_PATH = self._db_path
        self.db = database
        self.db.init_db()

        # cria um usuário base pra usar nos testes (reaproveitando core.auth)
        import core.auth as auth
        importlib.reload(auth)
        auth.DB_PATH = self._db_path
        self.auth = auth
        user = auth.create_user("fase2@teste.com", "usuariofase2", "senhaSegura123")
        self.user_id = user["id"]

    def tearDown(self):
        try:
            os.remove(self._db_path)
        except OSError:
            pass

    def test_users_and_sessions_tables_still_work_after_new_tables_added(self):
        """Confirma que adicionar tabelas novas não quebrou as antigas."""
        user = self.auth.get_user_by_email("fase2@teste.com")
        self.assertIsNotNone(user)
        self.assertEqual(user["email"], "fase2@teste.com")

    def test_create_project(self):
        project_id = self.db.create_project(self.user_id, "Meu primeiro projeto")
        self.assertIsInstance(project_id, int)
        self.assertGreater(project_id, 0)

    def test_create_video_without_project(self):
        video_id = self.db.create_video(
            user_id=self.user_id, original_filename="teste.mp4", storage_path="/fake/teste.mp4",
        )
        self.assertGreater(video_id, 0)
        videos = self.db.get_videos_for_user(self.user_id)
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0]["original_filename"], "teste.mp4")
        self.assertIsNone(videos[0]["project_id"])

    def test_create_video_linked_to_project(self):
        project_id = self.db.create_project(self.user_id, "Projeto X")
        video_id = self.db.create_video(
            user_id=self.user_id, original_filename="v.mp4", storage_path="/fake/v.mp4",
            project_id=project_id,
        )
        videos = self.db.get_videos_for_user(self.user_id)
        self.assertEqual(videos[0]["project_id"], project_id)

    def test_job_lifecycle(self):
        job_id = "job-teste-123"
        self.db.create_job(job_id, self.user_id, job_type="analyze")

        jobs = self.db.get_jobs_for_user(self.user_id)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["status"], "queued")
        self.assertIsNone(jobs[0]["finished_at"])

        self.db.update_job_status(job_id, status="running", step="transcribing")
        jobs = self.db.get_jobs_for_user(self.user_id)
        self.assertEqual(jobs[0]["status"], "running")
        self.assertEqual(jobs[0]["step"], "transcribing")
        self.assertIsNone(jobs[0]["finished_at"], "não deveria ter finished_at enquanto 'running'")

        self.db.update_job_status(job_id, status="done")
        jobs = self.db.get_jobs_for_user(self.user_id)
        self.assertEqual(jobs[0]["status"], "done")
        self.assertIsNotNone(jobs[0]["finished_at"], "deveria ter finished_at quando 'done'")

    def test_create_clip_linked_to_job_and_video(self):
        video_id = self.db.create_video(self.user_id, "v.mp4", "/fake/v.mp4")
        job_id = "job-clip-teste"
        self.db.create_job(job_id, self.user_id, job_type="generate", video_id=video_id)

        clip_id = self.db.create_clip(
            user_id=self.user_id, storage_path="/fake/clip1.mp4", video_id=video_id, job_id=job_id,
            clip_identifier="CLIP-ABC123", score=87.5, duration_seconds=22.0, mode="separate",
        )
        clips = self.db.get_clips_for_user(self.user_id)
        self.assertEqual(len(clips), 1)
        self.assertEqual(clips[0]["clip_identifier"], "CLIP-ABC123")
        self.assertEqual(clips[0]["score"], 87.5)
        self.assertEqual(clips[0]["video_id"], video_id)
        self.assertEqual(clips[0]["job_id"], job_id)

    def test_usage_event_recorded(self):
        event_id = self.db.record_usage_event(
            user_id=self.user_id, event_type="ai_call", provider="openai",
            model="gpt-4o-mini", estimated_cost_usd=0.0004,
        )
        self.assertGreater(event_id, 0)

    def test_videos_isolated_between_users(self):
        other_user = self.auth.create_user("outro@teste.com", "outrousuario", "outraSenha123")
        self.db.create_video(self.user_id, "meu.mp4", "/fake/meu.mp4")
        self.db.create_video(other_user["id"], "dele.mp4", "/fake/dele.mp4")

        my_videos = self.db.get_videos_for_user(self.user_id)
        other_videos = self.db.get_videos_for_user(other_user["id"])
        self.assertEqual(len(my_videos), 1)
        self.assertEqual(len(other_videos), 1)
        self.assertEqual(my_videos[0]["original_filename"], "meu.mp4")
        self.assertEqual(other_videos[0]["original_filename"], "dele.mp4")

    def test_init_db_is_idempotent(self):
        """Rodar init_db() de novo não deve apagar nem duplicar nada."""
        self.db.create_project(self.user_id, "Projeto Antes")
        self.db.init_db()  # roda de novo, como acontece toda vez que o servidor sobe
        with self.db.get_db() as conn:
            rows = conn.execute("SELECT * FROM projects WHERE user_id = ?", (self.user_id,)).fetchall()
        self.assertEqual(len(rows), 1, "init_db() rodando de novo não deveria duplicar nem apagar dados")


if __name__ == "__main__":
    unittest.main()
