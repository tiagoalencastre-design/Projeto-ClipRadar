"""
Testes de compatibilidade do arquivo final.

Motivo: um vídeo de montagem gerado pelo ClipRadar não abria no Windows
("unsupported encoding settings", 0x80004005). A causa era dupla:

  1. sem -pix_fmt yuv420p, o x264 pode sair num formato que players comuns
     não decodificam;
  2. o concat usava "-c copy" com pedaços de fps e base de tempo diferentes,
     produzindo timestamps fora de ordem.

Estes testes não renderizam vídeo: verificam a montagem dos comandos.
"""
from __future__ import annotations

import inspect
import unittest
from pathlib import Path

from core import montage
from core.montage import VIDEO_OUTPUT_ARGS


def _pairs(args: list[str]) -> dict:
    return {args[i]: args[i + 1] for i in range(0, len(args) - 1, 2)}


class TestOutputArguments(unittest.TestCase):
    def setUp(self):
        self.args = _pairs(VIDEO_OUTPUT_ARGS)

    def test_pixel_format_is_universally_supported(self):
        """yuv420p é o único formato que todo player e rede social aceita."""
        self.assertEqual(self.args["-pix_fmt"], "yuv420p")

    def test_frame_rate_is_fixed(self):
        """Sem fps fixo, pedaços não podem ser concatenados com segurança."""
        self.assertEqual(self.args["-r"], "30")

    def test_timescale_is_fixed(self):
        self.assertIn("-video_track_timescale", self.args)

    def test_audio_is_normalized(self):
        self.assertEqual(self.args["-ar"], "48000")
        self.assertEqual(self.args["-ac"], "2")

    def test_faststart_enabled(self):
        """Faz o vídeo começar a tocar antes de baixar inteiro."""
        self.assertEqual(self.args["-movflags"], "+faststart")

    def test_codecs_are_h264_and_aac(self):
        self.assertEqual(self.args["-c:v"], "libx264")
        self.assertEqual(self.args["-c:a"], "aac")


class TestNoUnsafeConcat(unittest.TestCase):
    SOURCE = Path("core/montage.py").read_text(encoding="utf-8")

    def test_concat_does_not_stream_copy(self):
        """'-c copy' num concat de pedaços heterogêneos quebra o arquivo."""
        concat_source = inspect.getsource(montage._concat_hard_cut)
        self.assertNotIn('"-c", "copy"', concat_source)

    def test_concat_uses_the_standard_output_args(self):
        concat_source = inspect.getsource(montage._concat_hard_cut)
        self.assertIn("VIDEO_OUTPUT_ARGS", concat_source)

    def test_every_encode_uses_the_standard_args(self):
        """Nenhum ponto pode ficar com parâmetros próprios e divergir."""
        self.assertNotIn('"-crf", "23",\n            "-c:a", "aac",', self.SOURCE)
        self.assertGreaterEqual(self.SOURCE.count("VIDEO_OUTPUT_ARGS"), 4)


if __name__ == "__main__":
    unittest.main()
