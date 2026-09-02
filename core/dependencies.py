"""
Peças compartilhadas entre os routers — Fase 6.

Aqui mora o que mais de um router precisa: a dependency de autenticação, o
nome do cookie de sessão e a URL base do app.

Existe pra evitar import circular: se o router de auth importasse do
api_server.py, e o api_server.py importasse o router, o Python entraria em
loop. Ambos importam daqui e o problema não acontece.
"""
from __future__ import annotations

import os

from fastapi import Cookie, HTTPException

from core import auth

SESSION_COOKIE_NAME = "cliparadar_session"
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000").rstrip("/")


def get_current_user(cliparadar_session: str | None = Cookie(default=None)) -> dict:
    """Dependency do FastAPI: garante que a rota só roda pra usuário logado.
    Comportamento idêntico ao que estava no api_server.py."""
    user = auth.get_user_from_session(cliparadar_session)
    if not user:
        raise HTTPException(401, "Sua sessão expirou ou você não está logado. Entre de novo.")
    return user
