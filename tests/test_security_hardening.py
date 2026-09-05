"""
Testes das proteções de segurança do front-end e da autenticação.

Cada bloco corresponde a um risco concreto verificado no código, não a uma
preocupação genérica.
"""
from __future__ import annotations

import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException

from core.rate_limit import RateLimiter
from core.url_policy import UrlNotAllowed, validate_download_url

APP_JS = Path("web/assets/app.js").read_text(encoding="utf-8")
AUTH_ROUTER = Path("core/routers/auth.py").read_text(encoding="utf-8")
API_SOURCE = Path("core/api_server.py").read_text(encoding="utf-8")


class TestHtmlEscaping(unittest.TestCase):
    """
    O texto das legendas vem da transcrição do vídeo; o nome do arquivo vem
    do upload. Ambos acabavam dentro de innerHTML sem tratamento.
    """

    def test_escape_helper_exists(self):
        self.assertIn("function esc(value)", APP_JS)

    def test_escape_covers_every_dangerous_character(self):
        helper = APP_JS[APP_JS.index("function esc(value)"):]
        helper = helper[:helper.index("\n}")]
        for char in ("&", "<", ">", '"', "'"):
            self.assertIn(f"/{char}/g", helper.replace("\\", ""), f"não escapa {char}")

    def test_ampersand_is_escaped_first(self):
        """Se & vier depois, &lt; viraria &amp;lt; e o escape se desfaz."""
        helper = APP_JS[APP_JS.index("function esc(value)"):]
        self.assertLess(helper.index("/&/g"), helper.index("/</g"))

    def test_transcript_is_escaped(self):
        self.assertIn("esc((c.transcript_excerpt", APP_JS)

    def test_filename_is_escaped(self):
        self.assertIn("esc(c.filename)", APP_JS)

    def test_phrase_text_is_escaped(self):
        self.assertIn("esc(p.text)", APP_JS)

    def test_recommendation_reason_is_escaped(self):
        """O motivo vem da transcrição ou do Edit Plan."""
        self.assertIn("esc(reason)", APP_JS)

    def test_urls_in_attributes_are_escaped(self):
        """Aspas numa URL quebrariam o atributo e permitiriam injetar outro."""
        self.assertIn("esc(c.video)", APP_JS)
        self.assertIn("esc(clip.video)", APP_JS)


class TestDownloadUrlPolicy(unittest.TestCase):
    """
    O yt-dlp aceita quase qualquer URL. Sem lista de permissões, o servidor
    faria requisições à rede interna em nome de quem pedisse.
    """

    def test_accepts_youtube(self):
        for url in (
            "https://www.youtube.com/watch?v=abc123",
            "https://youtu.be/abc123",
            "http://youtube.com/watch?v=abc",
            "https://m.youtube.com/watch?v=abc",
        ):
            self.assertEqual(validate_download_url(url), url)

    def test_rejects_local_file(self):
        with self.assertRaises(UrlNotAllowed):
            validate_download_url("file:///etc/passwd")

    def test_rejects_localhost(self):
        with self.assertRaises(UrlNotAllowed):
            validate_download_url("http://localhost:8000/api/clips")

    def test_rejects_cloud_metadata_endpoint(self):
        with self.assertRaises(UrlNotAllowed):
            validate_download_url("http://169.254.169.254/latest/meta-data/")

    def test_rejects_private_network(self):
        for url in ("http://192.168.0.1/", "http://10.0.0.5/", "http://127.0.0.1/"):
            with self.assertRaises(UrlNotAllowed):
                validate_download_url(url)

    def test_rejects_lookalike_domain(self):
        """'termina com youtube.com' aceitaria youtube.com.invasor.net."""
        with self.assertRaises(UrlNotAllowed):
            validate_download_url("https://youtube.com.invasor.net/x")

    def test_rejects_credentials_in_url(self):
        with self.assertRaises(UrlNotAllowed):
            validate_download_url("https://user:senha@youtube.com/watch?v=a")

    def test_rejects_other_video_sites(self):
        """Aceitar mais sites deve ser decisão consciente, não acidente."""
        with self.assertRaises(UrlNotAllowed):
            validate_download_url("https://vimeo.com/123")

    def test_error_message_does_not_leak_the_reason(self):
        """Mensagens distintas ajudariam a mapear o que o servidor aceita."""
        mensagens = set()
        for url in ("file:///etc/passwd", "http://localhost/", "https://vimeo.com/1"):
            try:
                validate_download_url(url)
            except UrlNotAllowed as e:
                mensagens.add(str(e))
        self.assertEqual(len(mensagens), 1)

    def test_endpoint_uses_the_policy(self):
        self.assertIn("validate_download_url(req.url)", API_SOURCE)


class TestRateLimiter(unittest.TestCase):
    def test_blocks_after_the_limit(self):
        limiter = RateLimiter(max_attempts=3, window_seconds=60, label="t")
        for _ in range(3):
            limiter.check("1.2.3.4")
        with self.assertRaises(HTTPException) as ctx:
            limiter.check("1.2.3.4")
        self.assertEqual(ctx.exception.status_code, 429)

    def test_includes_retry_after(self):
        limiter = RateLimiter(max_attempts=1, window_seconds=60, label="t")
        limiter.check("1.2.3.4")
        try:
            limiter.check("1.2.3.4")
        except HTTPException as e:
            self.assertIn("Retry-After", e.headers)

    def test_clients_are_independent(self):
        limiter = RateLimiter(max_attempts=2, window_seconds=60, label="t")
        limiter.check("1.1.1.1")
        limiter.check("1.1.1.1")
        limiter.check("2.2.2.2")   # outro IP não é afetado

    def test_window_slides(self):
        limiter = RateLimiter(max_attempts=2, window_seconds=1, label="t")
        limiter.check("x")
        limiter.check("x")
        time.sleep(1.1)
        limiter.check("x")   # janela passou

    def test_reset_clears_the_count(self):
        """Login certo não deve deixar o usuário penalizado."""
        limiter = RateLimiter(max_attempts=2, window_seconds=60, label="t")
        limiter.check("x")
        limiter.check("x")
        limiter.reset("x")
        limiter.check("x")


class TestAuthRoutesAreProtected(unittest.TestCase):
    def test_login_is_rate_limited(self):
        self.assertIn("login_limiter.check", AUTH_ROUTER)

    def test_successful_login_resets_the_counter(self):
        self.assertIn("login_limiter.reset", AUTH_ROUTER)

    def test_signup_is_rate_limited(self):
        self.assertIn("signup_limiter.check", AUTH_ROUTER)

    def test_resend_is_rate_limited(self):
        """Cada chamada dispara um e-mail — é o mais sensível dos três."""
        self.assertIn("resend_limiter.check", AUTH_ROUTER)

    def test_cookie_is_secure_over_https(self):
        self.assertIn("secure=APP_BASE_URL.lower().startswith(\"https://\")", AUTH_ROUTER)

    def test_cookie_keeps_httponly_and_samesite(self):
        self.assertIn("httponly=True", AUTH_ROUTER)
        self.assertIn('samesite="lax"', AUTH_ROUTER)


class TestVerificationTokenExpiry(unittest.TestCase):
    """O campo verification_sent_at era gravado e nunca consultado."""

    def test_expiry_helper_exists(self):
        from core.auth import VERIFICATION_TOKEN_HOURS, _token_expired
        self.assertGreater(VERIFICATION_TOKEN_HOURS, 0)

    def test_recent_token_is_valid(self):
        from core.auth import _token_expired
        agora = datetime.now(timezone.utc).isoformat()
        self.assertFalse(_token_expired(agora))

    def test_old_token_is_expired(self):
        from core.auth import _token_expired
        antigo = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        self.assertTrue(_token_expired(antigo))

    def test_missing_date_counts_as_expired(self):
        """Na dúvida, não confirma."""
        from core.auth import _token_expired
        self.assertTrue(_token_expired(None))
        self.assertTrue(_token_expired("data invalida"))

    def test_empty_token_is_rejected(self):
        from core.auth import verify_email_token
        self.assertFalse(verify_email_token(""))


if __name__ == "__main__":
    unittest.main()
