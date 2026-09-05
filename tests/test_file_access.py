"""
Testes de entrega autenticada de arquivos de mídia.

O PROBLEMA ORIGINAL: clipes e vídeos eram servidos por StaticFiles, que não
passa por autenticação. As APIs exigiam login para DESCOBRIR o caminho, mas
quem soubesse o caminho baixava sem sessão — e a storage_key aparece na URL
de todo clipe que o usuário abre no navegador.

Estes testes garantem que isso não volte.
"""
from __future__ import annotations

import shutil
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
    from core import api_server
    READY = True
except Exception:
    READY = False

API_SOURCE = Path("core/api_server.py").read_text(encoding="utf-8")


class TestNoUnauthenticatedMounts(unittest.TestCase):
    """A regressão mais provável: alguém reintroduzir o StaticFiles."""

    def test_clips_are_not_served_by_staticfiles(self):
        self.assertNotIn('app.mount("/files/clips"', API_SOURCE)

    def test_vods_are_not_served_by_staticfiles(self):
        self.assertNotIn('app.mount("/files/vods"', API_SOURCE)

    def test_assets_remain_public(self):
        """CSS, JS e logo precisam carregar antes do login."""
        self.assertIn('app.mount("/assets"', API_SOURCE)

    def test_routes_require_authentication(self):
        for route in ("/files/clips/{file_path:path}", "/files/vods/{file_path:path}"):
            section = API_SOURCE[API_SOURCE.index(route):]
            self.assertIn("Depends(get_current_user)", section[:400], route)


@unittest.skipUnless(READY, "fastapi não disponível")
class TestFileAccessControl(unittest.TestCase):
    OWNER = "test_owner_key"
    OTHER = "test_other_key"

    @classmethod
    def setUpClass(cls):
        cls.base = api_server.CLIPS_DIR
        for key in (cls.OWNER, cls.OTHER):
            (cls.base / key).mkdir(parents=True, exist_ok=True)
        (cls.base / cls.OWNER / "meu.mp4").write_bytes(b"A" * 5000)
        (cls.base / cls.OTHER / "seu.mp4").write_bytes(b"B" * 5000)
        cls.client = TestClient(api_server.app)

    @classmethod
    def tearDownClass(cls):
        for key in (cls.OWNER, cls.OTHER):
            shutil.rmtree(cls.base / key, ignore_errors=True)

    def _login_as(self, storage_key: str):
        api_server.app.dependency_overrides[api_server.get_current_user] = (
            lambda: {"id": 1, "storage_key": storage_key}
        )
        self.addCleanup(api_server.app.dependency_overrides.clear)

    def test_anonymous_request_is_rejected(self):
        """O ponto central: sem sessão, nem sabendo o caminho exato."""
        response = self.client.get(f"/files/clips/{self.OWNER}/meu.mp4")
        self.assertEqual(response.status_code, 401)

    def test_owner_can_download(self):
        self._login_as(self.OWNER)
        response = self.client.get(f"/files/clips/{self.OWNER}/meu.mp4")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.content), 5000)

    def test_cannot_read_another_users_file(self):
        self._login_as(self.OWNER)
        response = self.client.get(f"/files/clips/{self.OTHER}/seu.mp4")
        self.assertEqual(response.status_code, 404)

    def test_path_traversal_is_blocked(self):
        self._login_as(self.OWNER)
        response = self.client.get(f"/files/clips/{self.OWNER}/../{self.OTHER}/seu.mp4")
        self.assertEqual(response.status_code, 404)

    def test_missing_file_is_404(self):
        self._login_as(self.OWNER)
        self.assertEqual(
            self.client.get(f"/files/clips/{self.OWNER}/nao_existe.mp4").status_code, 404
        )

    def test_error_does_not_reveal_whether_file_exists(self):
        """Mensagens diferentes confirmariam a existência do arquivo alheio."""
        self._login_as(self.OWNER)
        alheio = self.client.get(f"/files/clips/{self.OTHER}/seu.mp4")
        inexistente = self.client.get(f"/files/clips/{self.OTHER}/nada.mp4")
        self.assertEqual(alheio.status_code, inexistente.status_code)
        self.assertEqual(alheio.json(), inexistente.json())


@unittest.skipUnless(READY, "fastapi não disponível")
class TestRangeRequests(unittest.TestCase):
    """
    Sem Range, o navegador não arrasta a barra do vídeo — e o Starlette
    usado aqui não implementa isso no FileResponse.
    """

    KEY = "test_range_key"

    @classmethod
    def setUpClass(cls):
        cls.base = api_server.CLIPS_DIR
        (cls.base / cls.KEY).mkdir(parents=True, exist_ok=True)
        (cls.base / cls.KEY / "v.mp4").write_bytes(bytes(range(256)) * 20)  # 5120 bytes
        cls.client = TestClient(api_server.app)
        api_server.app.dependency_overrides[api_server.get_current_user] = (
            lambda: {"id": 1, "storage_key": cls.KEY}
        )

    @classmethod
    def tearDownClass(cls):
        api_server.app.dependency_overrides.clear()
        shutil.rmtree(cls.base / cls.KEY, ignore_errors=True)

    def _get(self, **kwargs):
        return self.client.get(f"/files/clips/{self.KEY}/v.mp4", **kwargs)

    def test_full_response_advertises_range_support(self):
        response = self._get()
        self.assertEqual(response.headers.get("accept-ranges"), "bytes")

    def test_partial_content_returns_206(self):
        response = self._get(headers={"Range": "bytes=0-99"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(len(response.content), 100)
        self.assertEqual(response.headers["content-range"], "bytes 0-99/5120")

    def test_range_returns_the_right_bytes(self):
        """Fatia errada faria o vídeo tocar embaralhado."""
        whole = self._get().content
        part = self._get(headers={"Range": "bytes=1000-1099"}).content
        self.assertEqual(part, whole[1000:1100])

    def test_suffix_range_returns_the_tail(self):
        response = self._get(headers={"Range": "bytes=-50"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(len(response.content), 50)

    def test_open_ended_range_goes_to_the_end(self):
        response = self._get(headers={"Range": "bytes=5000-"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(len(response.content), 120)

    def test_range_beyond_file_is_416(self):
        self.assertEqual(self._get(headers={"Range": "bytes=99999-"}).status_code, 416)

    def test_caching_is_private(self):
        """Cache público exporia o clipe em proxy compartilhado."""
        self.assertIn("private", self._get().headers.get("cache-control", ""))


if __name__ == "__main__":
    unittest.main()
