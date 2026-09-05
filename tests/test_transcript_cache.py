"""
Testes do cache de transcrição.

A transcrição é a etapa mais cara do pipeline e a mais determinística: o
mesmo vídeo, com o mesmo modelo e idioma, sempre produz o mesmo texto.
Reanalisar sem cache desperdiça minutos de CPU a cada ajuste de scoring.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core import transcript_cache
from core.transcription import TranscriptSegment


def segments():
    return [
        TranscriptSegment(0.0, 5.0, "ontem eu tava jogando",
                          words=[{"start": 0.0, "end": 1.0, "word": "ontem"}]),
        TranscriptSegment(5.0, 9.0, "e consegui pegar todos"),
    ]


class _TempFiles(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.video = self.folder / "vod.mp4"
        self.video.write_bytes(b"conteudo do video " * 10000)

    def tearDown(self):
        self._tmp.cleanup()

    def path_for(self, model="medium", language="pt", video=None):
        return transcript_cache.cache_path(
            self.folder, video or self.video, model, language)


class TestFingerprint(_TempFiles):
    def test_same_content_same_fingerprint(self):
        self.assertEqual(
            transcript_cache.fingerprint(self.video),
            transcript_cache.fingerprint(self.video),
        )

    def test_different_content_different_fingerprint(self):
        other = self.folder / "outro.mp4"
        other.write_bytes(b"outro conteudo bem diferente " * 10000)
        self.assertNotEqual(
            transcript_cache.fingerprint(self.video),
            transcript_cache.fingerprint(other),
        )

    def test_renaming_keeps_the_fingerprint(self):
        """
        A chave é o CONTEÚDO, não o caminho. Importa porque o mesmo VOD pode
        ser enviado por dois usuários com nomes diferentes.
        """
        original = transcript_cache.fingerprint(self.video)
        renamed = self.folder / "outro_nome.mp4"
        self.video.rename(renamed)
        self.assertEqual(transcript_cache.fingerprint(renamed), original)

    def test_size_change_invalidates(self):
        """Vídeos de tamanhos diferentes nunca compartilham cache."""
        original = transcript_cache.fingerprint(self.video)
        self.video.write_bytes(b"conteudo do video " * 10001)
        self.assertNotEqual(transcript_cache.fingerprint(self.video), original)

    def test_missing_file_returns_none(self):
        """Sem impressão digital, o cache é ignorado e o Whisper roda."""
        self.assertIsNone(transcript_cache.fingerprint(self.folder / "nao_existe.mp4"))


class TestCacheKey(_TempFiles):
    def test_model_is_part_of_the_key(self):
        """Transcrição feita com 'base' não serve quando pedem 'medium'."""
        self.assertNotEqual(self.path_for(model="base"), self.path_for(model="medium"))

    def test_language_is_part_of_the_key(self):
        self.assertNotEqual(self.path_for(language="pt"), self.path_for(language="en"))

    def test_auto_language_has_its_own_key(self):
        self.assertNotEqual(self.path_for(language=None), self.path_for(language="pt"))

    def test_unreadable_video_has_no_cache_path(self):
        self.assertIsNone(self.path_for(video=self.folder / "nao_existe.mp4"))


class TestSaveAndLoad(_TempFiles):
    def test_round_trip_preserves_everything(self):
        path = self.path_for()
        transcript_cache.save(path, segments())
        loaded = transcript_cache.load(path)

        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0].text, "ontem eu tava jogando")
        self.assertEqual(loaded[0].start_seconds, 0.0)
        self.assertEqual(loaded[1].end_seconds, 9.0)

    def test_word_timestamps_survive(self):
        """Sem os tempos por palavra, a legenda karaokê para de funcionar."""
        path = self.path_for()
        transcript_cache.save(path, segments())
        loaded = transcript_cache.load(path)
        self.assertEqual(loaded[0].words[0]["word"], "ontem")
        self.assertEqual(loaded[0].words[0]["start"], 0.0)

    def test_missing_cache_returns_none(self):
        self.assertIsNone(transcript_cache.load(self.path_for()))

    def test_corrupted_cache_is_treated_as_absent(self):
        """
        Transcrever de novo custa tempo; devolver texto quebrado corromperia
        todos os clipes gerados a partir dele.
        """
        path = self.path_for()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{isto nao e json valido", encoding="utf-8")
        self.assertIsNone(transcript_cache.load(path))

    def test_empty_transcript_is_not_cached(self):
        self.assertFalse(transcript_cache.save(self.path_for(), []))

    def test_save_failure_does_not_raise(self):
        """Falha ao gravar cache não pode interromper o processamento."""
        self.assertFalse(transcript_cache.save(None, segments()))


class TestPipelineIntegration(unittest.TestCase):
    SOURCE = Path("core/pipeline.py").read_text(encoding="utf-8")

    def test_pipeline_checks_the_cache_before_transcribing(self):
        self.assertIn("transcript_cache.load(cached_at)", self.SOURCE)
        self.assertLess(
            self.SOURCE.index("transcript_cache.load"),
            self.SOURCE.index("transcript = transcribe("),
            "o pipeline transcreve antes de consultar o cache",
        )

    def test_pipeline_saves_after_transcribing(self):
        self.assertIn("transcript_cache.save(cached_at, transcript)", self.SOURCE)

    def test_cache_key_uses_the_configured_model(self):
        section = self.SOURCE[self.SOURCE.index("cached_at ="):]
        self.assertIn("model_size, language", section[:400])


if __name__ == "__main__":
    unittest.main()
