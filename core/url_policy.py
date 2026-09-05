"""
Política de URLs aceitas para download.

POR QUE ISTO EXISTE: o endpoint /api/videos/from-youtube entregava a URL
crua ao yt-dlp, que aceita praticamente qualquer coisa. Num serviço público
isso é mais que "baixar vídeo de outro site" — é o servidor fazendo
requisições em nome de quem pediu:

    file:///etc/passwd              lê arquivo local
    http://localhost:8000/api/...   fala com o próprio servidor, por dentro
    http://169.254.169.254/         metadados da instância, em nuvem
    http://192.168.0.1/             equipamentos da rede interna

É o padrão conhecido como SSRF. Uma lista de permissões resolve: em vez de
tentar adivinhar o que é perigoso, aceitamos só o que sabemos que é seguro.
"""
from __future__ import annotations

from urllib.parse import urlparse

# Domínios aceitos. Acrescentar aqui é uma decisão consciente, não um
# acidente — que é exatamente o ponto de uma lista de permissões.
ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}

ALLOWED_SCHEMES = {"http", "https"}


class UrlNotAllowed(ValueError):
    """URL recusada pela política."""


def validate_download_url(raw_url: str) -> str:
    """
    Devolve a URL se for aceitável; levanta UrlNotAllowed caso contrário.

    A mensagem de erro é a mesma para todos os motivos de recusa. Explicar
    "esquema inválido" versus "host não permitido" ajudaria alguém a mapear
    o que o servidor aceita.
    """
    url = (raw_url or "").strip()
    if not url:
        raise UrlNotAllowed("Informe o link do vídeo.")

    try:
        parsed = urlparse(url)
    except ValueError:
        raise UrlNotAllowed("Link inválido.")

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UrlNotAllowed("Link inválido. Use um endereço do YouTube.")

    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise UrlNotAllowed("Link inválido. Use um endereço do YouTube.")

    # Comparação exata contra a lista. Nada de "termina com youtube.com":
    # isso aceitaria "youtube.com.invasor.net".
    if host not in ALLOWED_HOSTS:
        raise UrlNotAllowed("Link inválido. Use um endereço do YouTube.")

    # Credenciais na URL (user:senha@host) confundem o parser de algumas
    # bibliotecas e não têm uso legítimo aqui.
    if parsed.username or parsed.password:
        raise UrlNotAllowed("Link inválido. Use um endereço do YouTube.")

    return url
