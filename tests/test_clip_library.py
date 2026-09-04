"""
Testes da Biblioteca de Clips e do preset padrão.

Motivo: os clipes gerados existiam no disco mas não apareciam em lugar
nenhum depois que o servidor reiniciava — o item "Clip library" da sidebar
não levava a nada.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from core.montage import DEFAULT_PRESET, EDIT_PRESETS

HTML = Path("web/index.html").read_text(encoding="utf-8")
API = Path("core/api_server.py").read_text(encoding="utf-8")


class TestClipLibraryEndpoint(unittest.TestCase):
    def test_endpoint_exists(self):
        self.assertIn('@app.get("/api/clips")', API)

    def test_reads_from_database_and_disk(self):
        """Banco dá os metadados; disco diz se o arquivo existe de verdade."""
        self.assertIn("ClipRepository.list_for_user", API)
        self.assertIn("clips_dir.glob", API)

    def test_is_protected_by_login(self):
        section = API[API.index('@app.get("/api/clips")'):]
        self.assertIn("Depends(get_current_user)", section[:400])

    def test_isolated_per_user(self):
        section = API[API.index('@app.get("/api/clips")'):]
        self.assertIn('_user_clips_dir(user["storage_key"])', section[:900])


class TestClipLibraryScreen(unittest.TestCase):
    def test_view_exists(self):
        self.assertIn('id="viewLibrary"', HTML)

    def test_sidebar_opens_the_library(self):
        """Antes, o item da sidebar levava de volta pra Home."""
        self.assertIn("setView('library')", HTML)
        self.assertNotIn(
            "document.getElementById('navLibrary').addEventListener('click', () => setView('home'));",
            HTML,
        )

    def test_library_fetches_the_endpoint(self):
        self.assertIn("fetch('/api/clips')", HTML)

    def test_empty_state_in_every_language(self):
        self.assertEqual(HTML.count("library_empty:"), 3)

    def test_translations_complete(self):
        for key in ("library_title:", "library_download:", "library_count:"):
            self.assertEqual(HTML.count(key), 3, f"falta tradução de {key}")


class TestPresetDefault(unittest.TestCase):
    def test_default_is_impact(self):
        """'clean' desliga zoom e destaque de palavra — pior em short-form."""
        self.assertEqual(DEFAULT_PRESET, "impact")

    def test_impact_enables_zoom_and_highlight(self):
        self.assertTrue(EDIT_PRESETS["impact"]["zoom_enabled"])
        self.assertTrue(EDIT_PRESETS["impact"]["highlight_words_enabled"])

    def test_old_presets_still_accepted_by_the_backend(self):
        """A API não pode quebrar com chamadas antigas que mandam 'clean'."""
        self.assertIn("clean", EDIT_PRESETS)
        self.assertIn("streamer", EDIT_PRESETS)

    def test_selector_removed_from_the_interface(self):
        self.assertNotIn('id="presetTabs"', HTML)
        self.assertNotIn('data-value="clean"', HTML)

    def test_no_orphan_javascript_references(self):
        """Referência a elemento removido quebraria o script inteiro."""
        self.assertNotIn("els.presetTabs", HTML)
        self.assertNotIn("reviewPresetTabs", HTML)

    def test_frontend_always_sends_impact(self):
        self.assertIn("const selectedPreset = 'impact';", HTML)


if __name__ == "__main__":
    unittest.main()
