"""
Testes da camada de repositórios — Fase 2.

Roda com:
    python -m unittest tests.test_repositories -v

Estes testes usam um banco TEMPORÁRIO. O data/cliparadar.db de verdade
nunca é tocado.
"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import database, repositories
from core.repositories import (
    Clip, ClipRepository, Job, JobRepository, Project, ProjectRepository,
    UsageEvent, UsageRepository, Video, VideoRepository,
)


class _TempDatabase(unittest.TestCase):
    """Cada teste roda num banco novo, isolado e descartável."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._db_path = Path(self._tmpdir.name) / "teste.db"
        self._patcher = patch.object(database, "DB_PATH", self._db_path)
        self._patcher.start()
        database.init_db()
        self.user_id = self._create_user("tiago@exemplo.com", "gringo")
        self.other_user_id = self._create_user("outro@exemplo.com", "outro")

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()

    def _create_user(self, email: str, username: str) -> int:
        with database.get_db() as conn:
            cursor = conn.execute(
                """INSERT INTO users
                   (email, username, password_hash, password_salt, storage_key,
                    email_verified, created_at)
                   VALUES (?, ?, 'hash', 'salt', ?, 1, '2026-01-01T00:00:00')""",
                (email, username, f"chave_{username}"),
            )
            conn.commit()
            return cursor.lastrowid


class TestProjectRepository(_TempDatabase):
    def test_create_returns_id(self):
        project_id = ProjectRepository.create(self.user_id, "Série Valorant")
        self.assertIsInstance(project_id, int)

    def test_get_returns_model_with_attributes(self):
        project_id = ProjectRepository.create(self.user_id, "Série Valorant")
        project = ProjectRepository.get(project_id, self.user_id)
        self.assertIsInstance(project, Project)
        self.assertEqual(project.name, "Série Valorant")

    def test_cannot_read_project_of_another_user(self):
        project_id = ProjectRepository.create(self.user_id, "Meu projeto")
        self.assertIsNone(ProjectRepository.get(project_id, self.other_user_id))

    def test_list_is_empty_for_new_user(self):
        self.assertEqual(ProjectRepository.list_for_user(self.other_user_id), [])


class TestVideoRepository(_TempDatabase):
    def test_create_and_get(self):
        video_id = VideoRepository.create(
            self.user_id, "gameplay.mp4", "data/vods/abc/gameplay.mp4",
            duration_seconds=1800.5,
        )
        video = VideoRepository.get(video_id, self.user_id)
        self.assertIsInstance(video, Video)
        self.assertEqual(video.original_filename, "gameplay.mp4")
        self.assertEqual(video.duration_seconds, 1800.5)
        self.assertEqual(video.source_type, "upload")

    def test_youtube_source_recorded(self):
        video_id = VideoRepository.create(
            self.user_id, "vod.mp4", "data/vods/abc/vod.mp4",
            source_type="youtube", source_url="https://youtu.be/xyz",
        )
        video = VideoRepository.get(video_id, self.user_id)
        self.assertEqual(video.source_type, "youtube")
        self.assertEqual(video.source_url, "https://youtu.be/xyz")

    def test_videos_isolated_between_users(self):
        VideoRepository.create(self.user_id, "meu.mp4", "data/vods/a/meu.mp4")
        self.assertEqual(len(VideoRepository.list_for_user(self.user_id)), 1)
        self.assertEqual(len(VideoRepository.list_for_user(self.other_user_id)), 0)

    def test_find_by_storage_path(self):
        VideoRepository.create(self.user_id, "x.mp4", "data/vods/a/x.mp4")
        found = VideoRepository.find_by_storage_path(self.user_id, "data/vods/a/x.mp4")
        self.assertIsNotNone(found)
        self.assertEqual(found.original_filename, "x.mp4")

    def test_find_by_storage_path_returns_none_when_absent(self):
        self.assertIsNone(
            VideoRepository.find_by_storage_path(self.user_id, "nao/existe.mp4")
        )


class TestJobRepository(_TempDatabase):
    def test_full_lifecycle(self):
        self.assertTrue(JobRepository.create("job-1", self.user_id, "generate"))

        job = JobRepository.get("job-1")
        self.assertIsInstance(job, Job)
        self.assertEqual(job.status, "queued")
        self.assertFalse(job.is_finished)

        JobRepository.update_status("job-1", "running", step="transcrevendo")
        job = JobRepository.get("job-1")
        self.assertEqual(job.status, "running")
        self.assertEqual(job.step, "transcrevendo")
        self.assertIsNone(job.finished_at)

        JobRepository.update_status("job-1", "done")
        job = JobRepository.get("job-1")
        self.assertTrue(job.is_finished)
        self.assertIsNotNone(job.finished_at)

    def test_error_is_recorded(self):
        JobRepository.create("job-erro", self.user_id, "generate")
        JobRepository.update_status("job-erro", "error", error="FFmpeg falhou")
        job = JobRepository.get("job-erro")
        self.assertEqual(job.status, "error")
        self.assertEqual(job.error, "FFmpeg falhou")
        self.assertTrue(job.is_finished)

    def test_get_unknown_job_returns_none(self):
        self.assertIsNone(JobRepository.get("nao-existe"))

    def test_list_unfinished_finds_interrupted_jobs(self):
        """O caso real: servidor reiniciou no meio do processamento."""
        JobRepository.create("job-ok", self.user_id, "generate")
        JobRepository.update_status("job-ok", "done")
        JobRepository.create("job-travado", self.user_id, "generate")
        JobRepository.update_status("job-travado", "running", step="montando")

        pendentes = JobRepository.list_unfinished(self.user_id)
        self.assertEqual(len(pendentes), 1)
        self.assertEqual(pendentes[0].id, "job-travado")

    def test_job_survives_restart(self):
        """
        O ponto central da Fase 2: o estado não mora mais só na RAM.
        Simulamos o restart abrindo o banco de novo, do zero.
        """
        JobRepository.create("job-persistente", self.user_id, "generate")
        JobRepository.update_status("job-persistente", "running", step="analisando")
        database.init_db()  # como se o servidor tivesse reiniciado
        job = JobRepository.get("job-persistente")
        self.assertIsNotNone(job)
        self.assertEqual(job.step, "analisando")


class TestClipRepository(_TempDatabase):
    def test_create_linked_to_job_and_video(self):
        video_id = VideoRepository.create(self.user_id, "v.mp4", "data/vods/a/v.mp4")
        JobRepository.create("job-c", self.user_id, "generate", video_id=video_id)
        clip_id = ClipRepository.create(
            self.user_id, "data/clips/a/clip1.mp4", video_id=video_id,
            job_id="job-c", score=8.7, duration_seconds=32.5, mode="impact",
        )
        clips = ClipRepository.list_for_job("job-c")
        self.assertEqual(len(clips), 1)
        self.assertIsInstance(clips[0], Clip)
        self.assertEqual(clips[0].score, 8.7)
        self.assertEqual(clips[0].mode, "impact")
        self.assertEqual(clips[0].id, clip_id)

    def test_clips_isolated_between_users(self):
        ClipRepository.create(self.user_id, "data/clips/a/c.mp4")
        self.assertEqual(len(ClipRepository.list_for_user(self.user_id)), 1)
        self.assertEqual(len(ClipRepository.list_for_user(self.other_user_id)), 0)


class TestUsageRepository(_TempDatabase):
    def test_record_and_list(self):
        UsageRepository.record(
            self.user_id, "video_processed", minutes_processed=30.0,
            provider="openai", model="gpt-4o-mini", estimated_cost_usd=0.004,
        )
        events = UsageRepository.list_for_user(self.user_id)
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], UsageEvent)
        self.assertEqual(events[0].provider, "openai")

    def test_total_minutes_sums_correctly(self):
        UsageRepository.record(self.user_id, "video_processed", minutes_processed=10.0)
        UsageRepository.record(self.user_id, "video_processed", minutes_processed=25.5)
        self.assertAlmostEqual(UsageRepository.total_minutes(self.user_id), 35.5)

    def test_total_minutes_zero_when_no_events(self):
        self.assertEqual(UsageRepository.total_minutes(self.other_user_id), 0.0)


class TestFailureSafety(_TempDatabase):
    """
    A garantia mais importante: falha de banco NUNCA derruba o pipeline.
    Um clipe perdido é pior que uma linha de histórico perdida.
    """

    def _broken_db(self):
        return patch.object(
            database, "get_db", side_effect=sqlite3.OperationalError("banco travado")
        )

    def test_write_failure_returns_none_instead_of_raising(self):
        with self._broken_db():
            self.assertIsNone(ProjectRepository.create(self.user_id, "x"))

    def test_job_create_failure_returns_false_instead_of_raising(self):
        with self._broken_db():
            self.assertFalse(JobRepository.create("j", self.user_id, "generate"))

    def test_read_failure_returns_empty_list(self):
        with self._broken_db():
            self.assertEqual(VideoRepository.list_for_user(self.user_id), [])
            self.assertEqual(JobRepository.list_for_user(self.user_id), [])

    def test_total_minutes_failure_returns_zero(self):
        with self._broken_db():
            self.assertEqual(UsageRepository.total_minutes(self.user_id), 0.0)

    def test_get_failure_returns_none(self):
        with self._broken_db():
            self.assertIsNone(JobRepository.get("qualquer"))


class TestOldFunctionsStillWork(_TempDatabase):
    """A Fase 2 é aditiva: o core/database.py continua funcionando igual."""

    def test_database_functions_untouched(self):
        project_id = database.create_project(self.user_id, "Direto pelo database.py")
        self.assertIsInstance(project_id, int)
        video_id = database.create_video(self.user_id, "v.mp4", "data/vods/v.mp4")
        self.assertEqual(len(database.get_videos_for_user(self.user_id)), 1)
        self.assertIsInstance(video_id, int)

    def test_both_layers_see_the_same_data(self):
        database.create_video(self.user_id, "antigo.mp4", "data/vods/antigo.mp4")
        VideoRepository.create(self.user_id, "novo.mp4", "data/vods/novo.mp4")
        self.assertEqual(len(database.get_videos_for_user(self.user_id)), 2)
        self.assertEqual(len(VideoRepository.list_for_user(self.user_id)), 2)


if __name__ == "__main__":
    unittest.main()
