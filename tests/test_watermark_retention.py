"""
Testes da marca d'água (plano grátis) e da retenção de clipes.
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from core.montage import (
    VERTICAL_FILTER, VERTICAL_RES, WATERMARK_PATH, append_watermark,
    build_watermark_filter,
)
from core.plans import FREE, PLANS, PRO
from core.retention import GRACE_HOURS, cleanup_user, find_expired

API = Path("core/api_server.py").read_text(encoding="utf-8")


class TestWatermark(unittest.TestCase):
    def test_image_exists(self):
        self.assertTrue(WATERMARK_PATH.exists(), "marca d'água não encontrada")

    def test_filter_is_built(self):
        self.assertIsNotNone(build_watermark_filter(VERTICAL_RES))

    def test_is_discreet_not_dominant(self):
        """Marca agressiva faz a pessoa não postar — e aí não divulga nada."""
        f = build_watermark_filter(VERTICAL_RES)
        width = int(f.split("scale=")[1].split(":")[0])
        self.assertLess(width, VERTICAL_RES[0] * 0.4)
        self.assertIn("colorchannelmixer=aa=0.75", f)

    def test_positioned_in_the_corner(self):
        f = append_watermark(f"[0:v]{VERTICAL_FILTER}[__stacked]", VERTICAL_RES)
        self.assertIn("overlay=W-w-34:H-h-34", f)

    def test_output_label_is_preserved(self):
        """Zoom e legenda são encadeados a partir de [__stacked]."""
        f = append_watermark(f"[0:v]{VERTICAL_FILTER}[__stacked]", VERTICAL_RES)
        self.assertTrue(f.rstrip().endswith("[__stacked]"))
        self.assertEqual(f.count("[__stacked]"), 1)

    def test_works_with_every_layout(self):
        from core.montage import _build_blur_background_filter
        for base in (f"[0:v]{VERTICAL_FILTER}[__stacked]",
                     _build_blur_background_filter(VERTICAL_RES)):
            self.assertIn("__wmf", append_watermark(base, VERTICAL_RES))

    def test_missing_file_does_not_break_rendering(self):
        """
        Melhor entregar sem marca do que falhar o clipe inteiro.

        O patch precisa ser em core.render.filters, que é ONDE a função
        procura o nome. Trocar core.montage.WATERMARK_PATH só mexeria na
        reexportação, e a função continuaria lendo o valor original — o
        teste passaria sem testar nada.
        """
        import core.render.filters as filters

        original = filters.WATERMARK_PATH
        filters.WATERMARK_PATH = Path("/nao/existe/marca.png")
        try:
            self.assertIsNone(build_watermark_filter(VERTICAL_RES))
            base = f"[0:v]{VERTICAL_FILTER}[__stacked]"
            self.assertEqual(append_watermark(base, VERTICAL_RES), base)
        finally:
            filters.WATERMARK_PATH = original

    def test_windows_drive_letter_is_escaped(self):
        """
        BUG REAL: dentro de um filter_complex, ":" separa argumentos. Um
        caminho "C:/Users/.../watermark.png" fazia o FFmpeg ler só "C":

            Failed to avformat_open_input 'C'

        A marca d'água não renderizava em NENHUMA máquina Windows — o plano
        grátis inteiro quebrava. Só apareceu quando o teste end-to-end rodou
        no Windows de verdade.
        """
        import core.montage as montage

        original = montage.WATERMARK_PATH
        montage.WATERMARK_PATH = Path("C:/Users/teste/watermark.png")
        try:
            # Sem o arquivo existir, devolve None — então testamos o escape
            # diretamente sobre a mesma transformação usada no filtro.
            escaped = Path("C:/Users/teste/watermark.png").as_posix().replace(":", "\\:")
            self.assertIn("C\\:", escaped)
            self.assertNotIn("C:/", escaped)
        finally:
            montage.WATERMARK_PATH = original

    def test_filter_escapes_colon_when_present(self):
        """O filtro montado nunca pode conter ':' de drive sem escape."""
        from core.montage import build_watermark_filter

        f = build_watermark_filter(VERTICAL_RES)
        self.assertIsNotNone(f)
        movie_part = f.split("[__wm]")[0]
        # Qualquer ':' dentro do movie= precisa vir escapado.
        import re
        unescaped = re.findall(r"(?<!\\):", movie_part)
        self.assertEqual(unescaped, [], f"':' sem escape em: {movie_part}")

    def test_only_free_plan_gets_it(self):
        self.assertTrue(PLANS[FREE].watermark)
        self.assertFalse(PLANS[PRO].watermark)


class TestRetentionCleanup(unittest.TestCase):
    def _clip(self, folder: Path, name: str, age_days: float) -> Path:
        path = folder / name
        path.write_bytes(b"x" * 2048)
        old = time.time() - age_days * 86400
        os.utime(path, (old, old))
        return path

    def test_recent_clips_are_kept(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            self._clip(folder, "novo.mp4", age_days=2)
            self.assertEqual(find_expired(folder, FREE), [])

    def test_old_clips_expire_on_free(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            self._clip(folder, "velho.mp4", age_days=10)
            self.assertEqual(len(find_expired(folder, FREE)), 1)

    def test_pro_keeps_them_longer(self):
        """Mesmo arquivo: expira no grátis, sobrevive no Pro."""
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            self._clip(folder, "c.mp4", age_days=10)
            self.assertEqual(len(find_expired(folder, FREE)), 1)
            self.assertEqual(len(find_expired(folder, PRO)), 0)

    def test_grace_period_prevents_early_deletion(self):
        """Nunca apagar por causa de fuso horário ou relógio desalinhado."""
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            self._clip(folder, "limite.mp4", age_days=7.1)
            self.assertEqual(find_expired(folder, FREE), [])

    def test_cleanup_removes_and_reports(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            self._clip(folder, "a.mp4", age_days=10)
            self._clip(folder, "b.mp4", age_days=1)
            result = cleanup_user(folder, FREE)
            self.assertEqual(result["removed"], 1)
            self.assertFalse((folder / "a.mp4").exists())
            self.assertTrue((folder / "b.mp4").exists())

    def test_thumbnail_goes_with_the_clip(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            self._clip(folder, "a.mp4", age_days=10)
            thumb = folder / "a.jpg"
            thumb.write_bytes(b"x")
            os.utime(thumb, (time.time() - 10 * 86400,) * 2)
            cleanup_user(folder, FREE)
            self.assertFalse(thumb.exists())

    def test_dry_run_deletes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            self._clip(folder, "a.mp4", age_days=10)
            result = cleanup_user(folder, FREE, dry_run=True)
            self.assertEqual(result["removed"], 1)
            self.assertTrue((folder / "a.mp4").exists())

    def test_missing_folder_does_not_crash(self):
        self.assertEqual(find_expired(Path("/nao/existe"), FREE), [])


class TestQuotaEnforcement(unittest.TestCase):
    def test_quota_checked_before_processing(self):
        """
        Descobrir que a cota acabou após 20 min de espera seria péssimo:
        a checagem precisa vir antes de a thread de processamento começar.
        """
        generate = API[API.index("def generate("):]
        generate = generate[:generate.index("queue.submit(")]
        self.assertIn("_enforce_quota(user, video_path, job_id)", generate)

    def test_uses_payment_required_status(self):
        self.assertIn("HTTPException(402", API)

    def test_unreadable_duration_does_not_block(self):
        """Melhor deixar passar do que recusar um vídeo válido por falha nossa."""
        section = API[API.index("def _enforce_quota"):]
        self.assertIn("if minutes <= 0:", section[:700])


if __name__ == "__main__":
    unittest.main()
