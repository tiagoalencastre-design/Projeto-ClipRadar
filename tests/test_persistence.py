"""
Testes da persistência do fluxo real — Fase 1 (confiabilidade).

Nada aqui depende de FFmpeg, Whisper, OpenAI ou internet. O banco é
temporário; o data/cliparadar.db de verdade nunca é tocado.
"""
from __future__ import annotations

import io
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from core import database, persistence
from core.repositories import ClipRepository, JobRepository, VideoRepository


class _TempDatabase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._patcher = patch.object(
            database, "DB_PATH", Path(self._tmpdir.name) / "teste.db"
        )
        self._patcher.start()
        database.init_db()
        self.user = self._create_user("tiago@exemplo.com", "gringo")
        self.other = self._create_user("outro@exemplo.com", "outro")

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()

    def _create_user(self, email: str, username: str) -> dict:
        with database.get_db() as conn:
            cursor = conn.execute(
                """INSERT INTO users (email, username, password_hash, password_salt,
                   storage_key, email_verified, created_at)
                   VALUES (?, ?, 'h', 's', ?, 1, '2026-01-01T00:00:00')""",
                (email, username, f"chave_{username}"),
            )
            conn.commit()
            return {"id": cursor.lastrowid, "email": email,
                    "storage_key": f"chave_{username}"}

    def _quiet(self):
        """Os logs poluem a saída dos testes — silenciamos só aqui."""
        return redirect_stdout(io.StringIO())


class TestVideoPersistence(_TempDatabase):
    def test_upload_is_registered(self):
        with self._quiet():
            video_id = persistence.register_video(
                self.user, "data/vods/chave_gringo/live.mp4", source_type="upload"
            )
        self.assertIsInstance(video_id, int)
        video = VideoRepository.get(video_id, self.user["id"])
        self.assertEqual(video.original_filename, "live.mp4")
        self.assertEqual(video.source_type, "upload")

    def test_youtube_download_records_source_url(self):
        with self._quiet():
            video_id = persistence.register_video(
                self.user, "data/vods/chave_gringo/vod.mp4",
                source_type="youtube", source_url="https://youtu.be/abc",
            )
        video = VideoRepository.get(video_id, self.user["id"])
        self.assertEqual(video.source_type, "youtube")
        self.assertEqual(video.source_url, "https://youtu.be/abc")

    def test_same_file_is_not_duplicated(self):
        """Reenviar o mesmo arquivo não pode criar duas linhas."""
        path = "data/vods/chave_gringo/live.mp4"
        with self._quiet():
            first = persistence.register_video(self.user, path)
            second = persistence.register_video(self.user, path)
        self.assertEqual(first, second)
        self.assertEqual(len(VideoRepository.list_for_user(self.user["id"])), 1)

    def test_find_video_id_returns_none_for_unknown_file(self):
        """Arquivos que já estavam na pasta antes desta fase não têm registro."""
        self.assertIsNone(persistence.find_video_id(self.user, "data/vods/antigo.mp4"))

    def test_videos_isolated_between_users(self):
        with self._quiet():
            persistence.register_video(self.user, "data/vods/a/meu.mp4")
        self.assertEqual(len(VideoRepository.list_for_user(self.user["id"])), 1)
        self.assertEqual(len(VideoRepository.list_for_user(self.other["id"])), 0)


class TestClipPersistence(_TempDatabase):
    def _fake_clips(self):
        """Formato que o montage.py devolve — sem renderizar nada."""
        return [
            {"clip_id": "CLIP-AAA", "video_path": "data/clips/a/1.mp4",
             "thumbnail_path": "data/clips/a/1.jpg", "score": 8.7,
             "duration_seconds": 32.5},
            {"clip_id": "CLIP-BBB", "video_path": "data/clips/a/2.mp4",
             "thumbnail_path": None, "score": 7.1, "duration_seconds": 18.0},
        ]

    def test_generated_clips_are_recorded(self):
        with self._quiet():
            video_id = persistence.register_video(self.user, "data/vods/a/live.mp4")
            JobRepository.create("job-1", self.user["id"], "generate", video_id)
            saved = persistence.record_generated_clips(
                self.user["id"], "job-1", self._fake_clips(),
                video_id=video_id, mode="separate",
            )
        self.assertEqual(saved, 2)
        clips = ClipRepository.list_for_job("job-1")
        self.assertEqual(len(clips), 2)
        self.assertEqual(clips[0].clip_identifier, "CLIP-AAA")
        self.assertEqual(clips[0].score, 8.7)
        self.assertEqual(clips[0].mode, "separate")

    def test_clips_are_linked_to_video_and_job(self):
        with self._quiet():
            video_id = persistence.register_video(self.user, "data/vods/a/live.mp4")
            JobRepository.create("job-2", self.user["id"], "generate", video_id)
            persistence.record_generated_clips(
                self.user["id"], "job-2", self._fake_clips()[:1], video_id=video_id
            )
        clip = ClipRepository.list_for_job("job-2")[0]
        self.assertEqual(clip.video_id, video_id)
        self.assertEqual(clip.job_id, "job-2")

    def test_manual_render_is_recorded(self):
        with self._quiet():
            clip_id = persistence.record_single_clip(
                self.user["id"], "data/clips/a/manual.mp4",
                clip_identifier="CLIP-XYZ", duration_seconds=25.0, mode="manual",
            )
        self.assertIsInstance(clip_id, int)
        clips = ClipRepository.list_for_user(self.user["id"])
        self.assertEqual(clips[0].mode, "manual")

    def test_empty_clip_list_records_nothing(self):
        with self._quiet():
            self.assertEqual(
                persistence.record_generated_clips(self.user["id"], "job-x", []), 0
            )


class TestInterruptedJobs(_TempDatabase):
    """O ponto central da fase: job não pode simplesmente sumir."""

    def test_running_jobs_are_marked_interrupted_on_restart(self):
        JobRepository.create("job-rodando", self.user["id"], "generate")
        JobRepository.update_status("job-rodando", "running", step="transcrevendo")

        with self._quiet():
            count = persistence.mark_orphan_jobs_as_interrupted()

        self.assertEqual(count, 1)
        job = JobRepository.get("job-rodando")
        self.assertEqual(job.status, "interrupted")
        self.assertIn("reiniciado", job.error)

    def test_finished_jobs_are_left_alone(self):
        JobRepository.create("job-ok", self.user["id"], "generate")
        JobRepository.update_status("job-ok", "done")
        JobRepository.create("job-erro", self.user["id"], "generate")
        JobRepository.update_status("job-erro", "error", error="FFmpeg falhou")

        with self._quiet():
            persistence.mark_orphan_jobs_as_interrupted()

        self.assertEqual(JobRepository.get("job-ok").status, "done")
        self.assertEqual(JobRepository.get("job-erro").error, "FFmpeg falhou")

    def test_running_twice_does_not_double_mark(self):
        JobRepository.create("j", self.user["id"], "generate")
        JobRepository.update_status("j", "running")
        with self._quiet():
            persistence.mark_orphan_jobs_as_interrupted()
            second = persistence.mark_orphan_jobs_as_interrupted()
        self.assertEqual(second, 0)

    def test_history_flags_interrupted_jobs(self):
        JobRepository.create("j", self.user["id"], "generate")
        JobRepository.update_status("j", "running")
        with self._quiet():
            persistence.mark_orphan_jobs_as_interrupted()
            history = persistence.list_user_history(self.user["id"])
        self.assertTrue(history["jobs"][0]["interrupted"])


class TestHistory(_TempDatabase):
    def test_history_has_three_sections(self):
        with self._quiet():
            history = persistence.list_user_history(self.user["id"])
        for section in ("videos", "jobs", "clips"):
            self.assertIn(section, history)

    def test_history_is_per_user(self):
        with self._quiet():
            persistence.register_video(self.user, "data/vods/a/meu.mp4")
            mine = persistence.list_user_history(self.user["id"])
            theirs = persistence.list_user_history(self.other["id"])
        self.assertEqual(len(mine["videos"]), 1)
        self.assertEqual(len(theirs["videos"]), 0)

    def test_history_survives_restart(self):
        with self._quiet():
            video_id = persistence.register_video(self.user, "data/vods/a/live.mp4")
            JobRepository.create("job-1", self.user["id"], "generate", video_id)
            JobRepository.update_status("job-1", "done")
            persistence.record_single_clip(
                self.user["id"], "data/clips/a/c.mp4", video_id=video_id, job_id="job-1"
            )
            database.init_db()  # como se o servidor tivesse reiniciado
            history = persistence.list_user_history(self.user["id"])
        self.assertEqual(len(history["videos"]), 1)
        self.assertEqual(len(history["clips"]), 1)
        self.assertEqual(history["jobs"][0]["status"], "done")


class TestNeverBreaksThePipeline(_TempDatabase):
    """Banco fora do ar não pode impedir a geração de clipes."""

    def _broken(self):
        return patch.object(
            database, "get_db", side_effect=sqlite3.OperationalError("banco travado")
        )

    def test_register_video_returns_none_instead_of_raising(self):
        with self._quiet(), self._broken():
            self.assertIsNone(persistence.register_video(self.user, "x.mp4"))

    def test_record_clips_returns_zero_instead_of_raising(self):
        with self._quiet(), self._broken():
            self.assertEqual(
                persistence.record_generated_clips(
                    self.user["id"], "j", [{"video_path": "a.mp4"}]
                ),
                0,
            )

    def test_interrupted_scan_survives_broken_database(self):
        with self._quiet(), self._broken():
            self.assertEqual(persistence.mark_orphan_jobs_as_interrupted(), 0)

    def test_history_returns_empty_sections_instead_of_raising(self):
        with self._quiet(), self._broken():
            history = persistence.list_user_history(self.user["id"])
        self.assertEqual(history["videos"], [])
        self.assertEqual(history["clips"], [])


if __name__ == "__main__":
    unittest.main()
