"""
Testes do layout "blur_background" (vídeo inteiro no centro, fundo borrado).

Não renderizam vídeo: validam a montagem do filtro e a integração do layout
com a API e a lista de opções.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from core.montage import (
    LAYOUT_OPTIONS, VERTICAL_RES, _build_blur_background_filter,
)


class TestBlurBackgroundFilter(unittest.TestCase):
    def setUp(self):
        self.filter = _build_blur_background_filter(VERTICAL_RES)

    def test_ends_with_the_label_the_pipeline_expects(self):
        """Zoom e legenda são encadeados a partir de [__stacked]."""
        self.assertTrue(self.filter.rstrip().endswith("[__stacked]"))

    def test_splits_the_source_into_background_and_foreground(self):
        self.assertIn("split=2", self.filter)

    def test_background_covers_the_whole_screen(self):
        """force_original_aspect_ratio=increase garante que não sobre buraco."""
        self.assertIn("force_original_aspect_ratio=increase", self.filter)
        self.assertIn(f"crop={VERTICAL_RES[0]}:{VERTICAL_RES[1]}", self.filter)

    def test_background_is_blurred(self):
        self.assertIn("boxblur", self.filter)

    def test_foreground_is_never_cropped(self):
        """O ponto do layout: nada das laterais pode ser perdido."""
        foreground = next(
            part for part in self.filter.split(";") if part.startswith("[__fg]")
        )
        self.assertNotIn("crop", foreground)
        self.assertIn(f"scale={VERTICAL_RES[0]}:-2", foreground)

    def test_foreground_is_centered(self):
        self.assertIn("overlay=(W-w)/2:(H-h)/2", self.filter)

    def test_even_height_for_h264(self):
        """scale=W:-2 mantém altura par; -1 poderia gerar ímpar e quebrar."""
        self.assertNotIn("scale=1080:-1", self.filter)

    def test_blur_strength_is_configurable(self):
        soft = _build_blur_background_filter(VERTICAL_RES, blur_strength=5)
        strong = _build_blur_background_filter(VERTICAL_RES, blur_strength=40)
        self.assertIn("boxblur=5:2", soft)
        self.assertIn("boxblur=40:2", strong)


class TestLayoutIntegration(unittest.TestCase):
    def test_layout_is_registered(self):
        self.assertIn("blur_background", LAYOUT_OPTIONS)

    def test_old_layouts_are_preserved(self):
        for layout in ("gameplay_full", "gameplay_facecam", "facecam_focus"):
            self.assertIn(layout, LAYOUT_OPTIONS)

    def test_api_accepts_the_new_layout(self):
        """Sem isto, a API rejeitaria a escolha do usuário com erro 422."""
        source = Path("core/api_server.py").read_text(encoding="utf-8")
        self.assertIn('"blur_background"', source)

    def test_frontend_offers_the_option_in_every_language(self):
        html = Path("web/index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count("layout_blur_background:"), 4)
        self.assertIn('data-value="blur_background"', html)

    def test_does_not_depend_on_face_detection(self):
        """Funciona em qualquer vídeo, com ou sem webcam."""
        self.assertNotIn("face", _build_blur_background_filter(VERTICAL_RES).lower())


if __name__ == "__main__":
    unittest.main()
