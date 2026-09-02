"""
Caminhos de arquivo por usuário — Fase 6.

Movido do api_server.py pra que os routers possam usar as mesmas funções
sem import circular. Comportamento idêntico ao de antes.

SEGURANÇA: as funções _resolve_* impedem que um usuário acesse arquivo de
outro mandando um nome como "../../outro_usuario/video.mp4". Toda entrada
vinda do navegador passa por elas.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException

VODS_DIR = Path("data/vods")
CLIPS_DIR = Path("data/clips")
CACHE_DIR = Path("data/cache")
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "web"
ASSETS_DIR = FRONTEND_DIR / "assets"

for _d in (VODS_DIR, CLIPS_DIR, CACHE_DIR, ASSETS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

SUPPORTED_VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv", ".webm")


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).name)


def user_vods_dir(storage_key: str) -> Path:
    d = VODS_DIR / storage_key
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_clips_dir(storage_key: str) -> Path:
    d = CLIPS_DIR / storage_key
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_cache_dir(storage_key: str) -> Path:
    d = CACHE_DIR / storage_key
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_vod_path(video_name: str, storage_key: str) -> Path:
    user_dir = user_vods_dir(storage_key)
    candidate = (user_dir / video_name).resolve()
    try:
        candidate.relative_to(user_dir.resolve())
    except ValueError:
        raise HTTPException(400, "Nome de vídeo inválido.")
    if not candidate.exists():
        raise HTTPException(404, f"Vídeo não encontrado: {video_name}")
    return candidate


def resolve_analysis_path(analysis_path: str, storage_key: str) -> Path:
    user_cache = user_cache_dir(storage_key)
    candidate = Path(analysis_path).resolve()
    try:
        candidate.relative_to(user_cache.resolve())
    except ValueError:
        raise HTTPException(400, "Caminho de análise inválido.")
    if not candidate.exists():
        raise HTTPException(404, "Análise não encontrada.")
    return candidate


def to_url(path: str | None) -> str | None:
    if not path:
        return None
    rel = Path(path).resolve().relative_to(CLIPS_DIR.resolve())
    return f"/files/clips/{rel.as_posix()}"


def to_vod_url(path: str) -> str:
    rel = Path(path).resolve().relative_to(VODS_DIR.resolve())
    return f"/files/vods/{rel.as_posix()}"
