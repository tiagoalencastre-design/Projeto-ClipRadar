"""
Router de sistema e páginas — Fase 6.

    GET /api/system/config
    GET /            (landing)
    GET /login
    GET /app         (painel)

URLs idênticas às de antes.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from core.app_config import get_app_config
from core.paths import FRONTEND_DIR

router = APIRouter(tags=["system"])


@router.get("/api/system/config")
def system_config() -> dict:
    """
    Confirma em que modo o servidor está rodando (development/mock/production)
    e quais feature flags estão ligadas — sem segredo nenhum aqui, só booleans.
    Público de propósito (útil pra confirmar o modo sem precisar do terminal).
    """
    return get_app_config().as_dict()


def _read_page(filename: str, friendly_name: str) -> str:
    page = FRONTEND_DIR / filename
    if not page.exists():
        raise HTTPException(500, f"{friendly_name} não encontrada em web/{filename}")
    return page.read_text(encoding="utf-8")


@router.get("/", response_class=HTMLResponse)
def serve_landing() -> str:
    return _read_page("landing.html", "Página inicial")


@router.get("/login", response_class=HTMLResponse)
def serve_login() -> str:
    return _read_page("login.html", "Página de login")


@router.get("/app", response_class=HTMLResponse)
def serve_app() -> str:
    return _read_page("index.html", "Painel")
