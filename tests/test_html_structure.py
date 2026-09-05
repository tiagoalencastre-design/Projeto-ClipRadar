"""
Testes de estrutura do HTML.

MOTIVO REAL: ao remover o seletor de presets, as tags de ABERTURA saíram e
as de FECHAMENTO ficaram. Duas </div> sobrando fecharam os containers cedo
demais, e a página inteira saiu do lugar — a barra lateral, o botão de
gerar e o conteúdo ficaram flutuando fora do layout.

Nenhum teste de Python pegava isso: o servidor subia normalmente e a API
respondia certo. Só o navegador mostrava o estrago.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

PAGES = ("web/index.html", "web/landing.html", "web/login.html")

PAIRED_TAGS = ("div", "section", "aside", "main", "ul", "select", "form", "nav")


def _markup_only(html: str) -> str:
    """Só o HTML: fora <script> e <style>, que têm chaves e strings capazes
    de confundir a contagem."""
    html = re.sub(r"<script\b.*?</script>", "", html, flags=re.S)
    html = re.sub(r"<style\b.*?</style>", "", html, flags=re.S)
    return html


class TestTagBalance(unittest.TestCase):
    def test_every_page_has_balanced_tags(self):
        for page in PAGES:
            markup = _markup_only(Path(page).read_text(encoding="utf-8"))
            for tag in PAIRED_TAGS:
                opens = len(re.findall(rf"<{tag}\b", markup))
                closes = len(re.findall(rf"</{tag}>", markup))
                self.assertEqual(
                    opens, closes,
                    f"{page}: <{tag}> abertas={opens} fechadas={closes}",
                )

    def test_never_closes_more_than_it_opens(self):
        """Fechar tag que não foi aberta é o que desloca o layout inteiro."""
        for page in PAGES:
            markup = _markup_only(Path(page).read_text(encoding="utf-8"))
            depth = 0
            for line_number, line in enumerate(markup.split("\n"), start=1):
                depth += len(re.findall(r"<div\b", line))
                depth -= len(re.findall(r"</div>", line))
                self.assertGreaterEqual(
                    depth, 0,
                    f"{page}, linha {line_number}: </div> a mais",
                )
            self.assertEqual(depth, 0, f"{page}: sobraram {depth} <div> abertas")


class TestNoOrphanReferences(unittest.TestCase):
    """Elemento removido do HTML mas ainda referenciado no JS quebra tudo."""

    def test_every_getelementbyid_target_exists(self):
        """
        O JS vive em web/assets/app.js desde a separação. Este teste LÊ OS
        DOIS arquivos de propósito: se lesse só o index.html, não acharia
        nenhum getElementById e passaria sem testar nada — falha silenciosa,
        o pior tipo.
        """
        html = Path("web/index.html").read_text(encoding="utf-8")
        js = Path("web/assets/app.js").read_text(encoding="utf-8")

        ids_in_html = set(re.findall(r'id="([A-Za-z0-9_-]+)"', html))
        # Elementos criados em tempo de execução pelo próprio script.
        ids_in_html |= set(re.findall(r'id="([A-Za-z0-9_-]+)"', js))
        ids_in_html |= set(re.findall(r"\.id = '([A-Za-z0-9_-]+)'", js))

        referenced = set(re.findall(r"getElementById\('([A-Za-z0-9_-]+)'\)", js))
        self.assertGreater(len(referenced), 20, "não encontrei o JS — teste vazio?")

        missing = referenced - ids_in_html
        self.assertEqual(missing, set(), f"JS busca ids que não existem: {sorted(missing)}")

    def test_html_references_the_external_assets(self):
        """Se o link quebrar, a página carrega sem estilo e sem JS."""
        html = Path("web/index.html").read_text(encoding="utf-8")
        self.assertIn('href="/assets/app.css"', html)
        self.assertIn('src="/assets/app.js"', html)
        self.assertTrue(Path("web/assets/app.css").exists())
        self.assertTrue(Path("web/assets/app.js").exists())

    def test_no_inline_style_or_script_left_behind(self):
        """Bloco esquecido dentro do HTML sobrescreveria o arquivo externo."""
        html = Path("web/index.html").read_text(encoding="utf-8")
        self.assertNotIn("<style>", html)
        self.assertIn('<script src="/assets/app.js">', html)


if __name__ == "__main__":
    unittest.main()
