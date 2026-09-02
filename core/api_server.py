"""
Servidor local (roda só no seu PC, sem nuvem) que expõe o pipeline de análise
e montagem como uma API, pra um front-end HTML/CSS/JS de verdade poder
chamar. Agora com contas de usuário (e-mail + senha + confirmação por
e-mail via Resend) — cada pessoa só acessa seus próprios vídeos/clipes.

⚠️ IMPORTANTE: isto é um servidor de BETA FECHADO — não é uma API pública
robusta. As proteções abaixo reduzem risco nesse uso restrito, mas não
substituem uma infraestrutura de produção de verdade.

Instalar (uma vez):
    pip install fastapi uvicorn python-multipart yt-dlp python-dotenv requests

Rodar:
    uvicorn core.api_server:app --reload --port 8000
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Literal

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pipeline import load_config, run_pipeline, default_output_path, PipelineError
from core.montage import run_montage, MontageError, export_separate_clips, get_candidates_for_review, render_single_clip
from core.thumbnail import extract_thumbnail, derive_thumbnail_text
from core.database import init_db
from core import auth
from core import email_service
from core.app_config import get_app_config
from core.job_store import PersistentJobStore
from core.dependencies import APP_BASE_URL, SESSION_COOKIE_NAME, get_current_user
from core.routers import auth as auth_router
from core.routers import system as system_router
from core import persistence
from core.observability import StageTimer, log_event
from core.repositories import VideoRepository

VODS_DIR = Path("data/vods")
CLIPS_DIR = Path("data/clips")
CACHE_DIR = Path("data/cache")
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "web"
ASSETS_DIR = FRONTEND_DIR / "assets"

VODS_DIR.mkdir(parents=True, exist_ok=True)
CLIPS_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

init_db()  # cria as tabelas de usuário/sessão se ainda não existirem

# FASE 1 (confiabilidade): o estado de execução vive na memória, então jobs
# que estavam rodando quando o processo morreu não voltam sozinhos. Em vez
# de sumirem da tela, ficam marcados como 'interrupted' — o usuário vê o
# que aconteceu.
persistence.mark_orphan_jobs_as_interrupted()

# Fase 1: mostra claramente em que modo o servidor está subindo — sem isso,
# é fácil esquecer se IA está de fato bloqueada ou não nesta sessão.
_app_config = get_app_config()
print(f"[ClipRadar] Modo atual: {_app_config.mode.upper()}")
print(f"[ClipRadar] Feature flags: {_app_config.as_dict()['flags']}")

app = FastAPI(title="ClipRadar API")
app.mount("/files/clips", StaticFiles(directory=str(CLIPS_DIR)), name="clips")
app.mount("/files/vods", StaticFiles(directory=str(VODS_DIR)), name="vods")
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

# FASE 6: rotas de /api/auth/* agora vivem em core/routers/auth.py.
# As URLs continuam exatamente as mesmas — o front-end não muda.
app.include_router(auth_router.router)
app.include_router(system_router.router)

# ---------- Limites de segurança ----------
SUPPORTED_VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv", ".webm")
MAX_CONCURRENT_JOBS = 2
MAX_UPLOAD_SIZE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB
JOB_EXPIRY_SECONDS = 24 * 60 * 60

# FASE 2b: continuam funcionando como dicionários comuns (todo o código
# abaixo permanece igual), mas agora espelham status/step/error no banco
# automaticamente. A memória segue sendo a fonte da verdade do que está
# rodando AGORA; o banco é o histórico que sobrevive ao restart.
jobs = PersistentJobStore("generate")
download_jobs = PersistentJobStore("youtube_download")
analyze_jobs = PersistentJobStore("analyze")

_active_jobs_lock = threading.Lock()
_active_job_count = 0


# ---------- Modelos de request ----------
class GenerateRequest(BaseModel):
    video_name: str
    mode: Literal["montage", "separate"] = "montage"
    orientation: Literal["vertical", "horizontal"] = "vertical"
    platform: Literal["tiktok", "reels", "shorts", "sem_preferencia"] | None = None
    burn_captions: bool = True
    subtitle_style: Literal["classic", "bold_yellow", "minimal_top", "boxed"] = "classic"
    preset: Literal["clean", "impact", "streamer"] = "clean"


class YoutubeDownloadRequest(BaseModel):
    url: str


class AnalyzeRequest(BaseModel):
    video_name: str


class RenderClipRequest(BaseModel):
    analysis_path: str
    clip_id: str
    start_seconds: float
    end_seconds: float
    title: str | None = None
    orientation: Literal["vertical", "horizontal"] = "vertical"
    platform: Literal["tiktok", "reels", "shorts", "sem_preferencia"] | None = None
    burn_captions: bool = True
    subtitle_style: Literal["classic", "bold_yellow", "minimal_top", "boxed"] = "classic"
    preset: Literal["clean", "impact", "streamer"] = "clean"
    layout: Literal["gameplay_full", "gameplay_facecam", "facecam_focus"] = "gameplay_facecam"


# ---------- Autenticação ----------
# FASE 6: get_current_user, SESSION_COOKIE_NAME e APP_BASE_URL agora moram
# em core/dependencies.py, compartilhados entre api_server.py e os routers.


# ---------- Helpers de arquivo (agora por usuário, via storage_key) ----------
def _safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    return name.strip() or "video"


def _user_vods_dir(storage_key: str) -> Path:
    d = VODS_DIR / storage_key
    d.mkdir(parents=True, exist_ok=True)
    return d


def _user_clips_dir(storage_key: str) -> Path:
    d = CLIPS_DIR / storage_key
    d.mkdir(parents=True, exist_ok=True)
    return d


def _user_cache_dir(storage_key: str) -> Path:
    d = CACHE_DIR / storage_key
    d.mkdir(parents=True, exist_ok=True)
    return d


def _resolve_vod_path(video_name: str, storage_key: str) -> Path:
    user_dir = _user_vods_dir(storage_key)
    candidate = (user_dir / video_name).resolve()
    try:
        candidate.relative_to(user_dir.resolve())
    except ValueError:
        raise HTTPException(400, "Nome de vídeo inválido.")
    if not candidate.exists():
        raise HTTPException(404, f"Vídeo não encontrado: {video_name}")
    return candidate


def _resolve_analysis_path(analysis_path: str, storage_key: str) -> Path:
    user_cache = _user_cache_dir(storage_key)
    candidate = Path(analysis_path).resolve()
    try:
        candidate.relative_to(user_cache.resolve())
    except ValueError:
        raise HTTPException(400, "Caminho de análise inválido.")
    if not candidate.exists():
        raise HTTPException(404, "Análise não encontrada.")
    return candidate


def _to_url(path: str | None) -> str | None:
    if not path:
        return None
    rel = Path(path).resolve().relative_to(CLIPS_DIR.resolve())
    return f"/files/clips/{rel.as_posix()}"


def _to_vod_url(path: str) -> str:
    rel = Path(path).resolve().relative_to(VODS_DIR.resolve())
    return f"/files/vods/{rel.as_posix()}"


def _cleanup_old_jobs() -> None:
    cutoff = time.time() - JOB_EXPIRY_SECONDS
    for store in (jobs, download_jobs, analyze_jobs):
        expired = [jid for jid, data in store.items() if data.get("created_at", time.time()) < cutoff]
        for jid in expired:
            del store[jid]


def _try_acquire_job_slot() -> bool:
    global _active_job_count
    with _active_jobs_lock:
        if _active_job_count >= MAX_CONCURRENT_JOBS:
            return False
        _active_job_count += 1
        return True


def _release_job_slot() -> None:
    global _active_job_count
    with _active_jobs_lock:
        _active_job_count = max(0, _active_job_count - 1)


def _check_job_owner(store: dict, job_id: str, user_id: int) -> dict:
    """Confirma que o job pertence a quem está pedindo — evita um usuário
    ver o status/resultado do processamento de outro só adivinhando o ID."""
    if job_id not in store:
        raise HTTPException(404, "Job não encontrado")
    data = store[job_id]
    if data.get("user_id") != user_id:
        raise HTTPException(404, "Job não encontrado")
    return data


# ============================================================
# Vídeos (agora tudo protegido por login + isolado por usuário)
# ============================================================
@app.get("/api/videos")
def list_videos(user: dict = Depends(get_current_user)) -> dict:
    """
    FASE 1: a chave "videos" continua sendo a lista de nomes lida do disco —
    é o que o front-end já consome, e não pode mudar de formato.

    O disco continua sendo a fonte da verdade aqui de propósito: um arquivo
    apagado à mão não deve continuar aparecendo só porque está no banco.
    O que o banco acrescenta vai em "registered", com os metadados
    (origem, data, duração) que o disco não sabe informar.
    """
    _cleanup_old_jobs()
    user_dir = _user_vods_dir(user["storage_key"])
    videos = []
    for ext in SUPPORTED_VIDEO_EXTENSIONS:
        videos.extend(p.name for p in user_dir.glob(f"*{ext}"))
    videos = sorted(videos)

    known = {
        v.original_filename: {
            "id": v.id, "source_type": v.source_type,
            "created_at": v.created_at, "duration_seconds": v.duration_seconds,
        }
        for v in VideoRepository.list_for_user(user["id"])
    }
    return {
        "videos": videos,
        "registered": [{"filename": name, **known[name]} for name in videos if name in known],
    }


@app.get("/api/history")
def user_history(user: dict = Depends(get_current_user)) -> dict:
    """
    Histórico persistido: vídeos, jobs e clipes. Sobrevive a restart.

    Jobs marcados como "interrupted" são os que estavam rodando quando o
    servidor caiu — aparecem com essa marca em vez de sumir.
    """
    return persistence.list_user_history(user["id"])


@app.post("/api/videos/upload")
async def upload_video(file: UploadFile = File(...), user: dict = Depends(get_current_user)) -> dict:
    if not file.filename.lower().endswith(SUPPORTED_VIDEO_EXTENSIONS):
        raise HTTPException(400, f"Formato não suportado. Use um destes: {', '.join(SUPPORTED_VIDEO_EXTENSIONS)}.")

    user_dir = _user_vods_dir(user["storage_key"])
    safe_name = _safe_filename(file.filename)
    dest_path = user_dir / safe_name
    try:
        dest_path.resolve().relative_to(user_dir.resolve())
    except ValueError:
        raise HTTPException(400, "Nome de arquivo inválido.")

    counter = 1
    while dest_path.exists():
        dest_path = user_dir / f"{Path(safe_name).stem}_{counter}{Path(safe_name).suffix}"
        counter += 1

    bytes_written = 0
    try:
        with open(dest_path, "wb") as out_file:
            while chunk := await file.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > MAX_UPLOAD_SIZE_BYTES:
                    out_file.close()
                    dest_path.unlink(missing_ok=True)
                    raise HTTPException(413, f"Arquivo grande demais. Limite: {MAX_UPLOAD_SIZE_BYTES // (1024**3)} GB.")
                out_file.write(chunk)
    except HTTPException:
        raise
    except Exception:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(500, "Falha ao salvar o arquivo enviado.")

    video_id = persistence.register_video(user, dest_path, source_type="upload")
    return {"video_name": dest_path.name, "video_id": video_id}


@app.post("/api/videos/from-youtube")
def start_youtube_download(req: YoutubeDownloadRequest, user: dict = Depends(get_current_user)) -> dict:
    _cleanup_old_jobs()
    if not req.url.strip():
        raise HTTPException(400, "URL vazia.")

    job_id = str(uuid.uuid4())
    download_jobs[job_id] = {"status": "running", "user_id": user["id"], "created_at": time.time()}
    thread = threading.Thread(
        target=_run_youtube_download, args=(job_id, req.url, user), daemon=True
    )
    thread.start()
    return {"job_id": job_id}


def _run_youtube_download(job_id: str, url: str, user: dict) -> None:
    storage_key = user["storage_key"]
    try:
        import yt_dlp
    except ImportError:
        download_jobs[job_id].update({"status": "error", "error": "yt-dlp não instalado."})
        return

    user_dir = _user_vods_dir(storage_key)
    try:
        ydl_opts = {
            "format": "best[ext=mp4]/best",
            "outtmpl": str(user_dir / "%(title)s.%(ext)s"),
            "merge_output_format": "mp4",
            "restrictfilenames": True,
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = Path(ydl.prepare_filename(info))
            final_path = filename.with_suffix(".mp4")
            if not final_path.exists() and filename.exists():
                final_path = filename
        video_id = persistence.register_video(
            user, final_path, source_type="youtube", source_url=url
        )
        download_jobs[job_id].update({
            "status": "done", "video_name": final_path.name, "video_id": video_id,
        })
    except Exception as e:
        print(f"[ClipRadar] Falha ao baixar vídeo do YouTube: {e}")
        download_jobs[job_id].update({"status": "error", "error": "Falha ao baixar o vídeo. Confira o link."})


@app.get("/api/videos/download-status/{job_id}")
def youtube_download_status(job_id: str, user: dict = Depends(get_current_user)) -> dict:
    return _check_job_owner(download_jobs, job_id, user["id"])


# ============================================================
# Análise / montagem / clipes separados (fluxo já existente)
# ============================================================
def _run_job(
    job_id: str, video_path: Path, user: dict, mode: str, orientation: str,
    platform: str | None, burn_captions: bool, subtitle_style: str, preset: str,
) -> None:
    storage_key = user["storage_key"]
    video_id = persistence.find_video_id(user, video_path)
    log_event(stage="job_iniciado", job_id=job_id, video_id=video_id,
              user_id=user["id"], operation=mode)
    try:
        config = load_config()
        ai_title_config = config.get("ai_title", {})
        edit_plan_config = config.get("edit_plan", {})
        analysis_path = default_output_path(str(video_path), output_dir=str(_user_cache_dir(storage_key)))
        moments = run_pipeline(str(video_path), config, analysis_path)

        analysis_data = json.loads(Path(analysis_path).read_text(encoding="utf-8"))
        top_preview = sorted(analysis_data["moments"], key=lambda m: m["score"], reverse=True)[:4]
        preview_cards = []
        previews_dir = _user_clips_dir(storage_key) / "_previews"
        previews_dir.mkdir(parents=True, exist_ok=True)
        for m in top_preview:
            thumb_path = previews_dir / f"preview_{m['clip_id']}.jpg"
            label = derive_thumbnail_text(m.get("transcript_excerpt", ""), max_words=3) or "MOMENTO"
            extract_thumbnail(analysis_data["video_path"], m["start_seconds"], str(thumb_path), text=None)
            preview_cards.append({"score": m["score"], "label": label, "image": _to_url(str(thumb_path))})

        output_dir = str(_user_clips_dir(storage_key))

        if mode == "separate":
            clips = export_separate_clips(
                analysis_path=analysis_path, platform=platform, orientation=orientation,
                burn_captions=burn_captions, subtitle_style=subtitle_style,
                dynamic_zoom=True, trim_dead_air=False, auto_face_crop=True,
                ai_title_config=ai_title_config, edit_plan_config=edit_plan_config,
                preset=preset, output_dir=output_dir,
            )
            jobs[job_id].update({
                "status": "done", "mode": "separate", "total_moments": len(moments),
                "preview_cards": preview_cards,
                "clips": [
                    {
                        "clip_id": c["clip_id"], "score": c["score"],
                        "duration_seconds": c.get("duration_seconds"),
                        "video": _to_url(c["video_path"]), "thumbnail": _to_url(c["thumbnail_path"]),
                        "edit_plan": c.get("edit_plan"),
                        "breakdown": c.get("breakdown"),
                    }
                    for c in clips
                ],
            })
            persistence.record_generated_clips(
                user_id=user["id"], job_id=job_id, clips=clips,
                video_id=video_id, mode="separate",
            )
        else:
            final_video, thumbnail, edit_plan, duration = run_montage(
                analysis_path=analysis_path, auto=True, platform=platform, orientation=orientation,
                burn_captions=burn_captions, subtitle_style=subtitle_style,
                dynamic_zoom=True, trim_dead_air=False, auto_face_crop=True,
                ai_title_config=ai_title_config, edit_plan_config=edit_plan_config,
                preset=preset, output_dir=output_dir,
            )
            jobs[job_id].update({
                "status": "done", "mode": "montage", "total_moments": len(moments),
                "final_video": _to_url(final_video), "thumbnail": _to_url(thumbnail),
                "duration_seconds": round(duration, 1) if duration else None,
                "preview_cards": preview_cards, "edit_plan": edit_plan,
            })
            persistence.record_single_clip(
                user_id=user["id"], storage_path=str(final_video),
                video_id=video_id, job_id=job_id,
                thumbnail_path=str(thumbnail) if thumbnail else None,
                duration_seconds=round(duration, 1) if duration else None,
                mode="montage",
            )
    except (PipelineError, MontageError) as e:
        jobs[job_id].update({"status": "error", "error": str(e)})
        log_event(stage="job_falhou", status="error", job_id=job_id,
                  video_id=video_id, user_id=user["id"], error=str(e))
    except Exception:
        print(f"[ClipRadar] Erro inesperado no job {job_id}:\n{traceback.format_exc()}")
        jobs[job_id].update({"status": "error", "error": "Erro interno inesperado. Tente novamente."})
        log_event(stage="job_falhou", status="error", job_id=job_id,
                  video_id=video_id, user_id=user["id"], error="erro interno")
    finally:
        _release_job_slot()


@app.post("/api/generate")
def generate(req: GenerateRequest, user: dict = Depends(get_current_user)) -> dict:
    _cleanup_old_jobs()
    video_path = _resolve_vod_path(req.video_name, user["storage_key"])

    if not _try_acquire_job_slot():
        raise HTTPException(429, f"Já tem {MAX_CONCURRENT_JOBS} vídeo(s) sendo processado(s). Tente depois.")

    job_id = str(uuid.uuid4())
    # video_id vai no dicionário: o PersistentJobStore o grava na tabela jobs,
    # ligando o processamento ao vídeo de origem.
    jobs[job_id] = {
        "status": "running", "step": "queued", "user_id": user["id"],
        "video_id": persistence.find_video_id(user, video_path),
        "created_at": time.time(),
    }
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, video_path, user, req.mode, req.orientation, req.platform,
              req.burn_captions, req.subtitle_style, req.preset),
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
def status(job_id: str, user: dict = Depends(get_current_user)) -> dict:
    return _check_job_owner(jobs, job_id, user["id"])


# ============================================================
# Revisão manual (analisar sem renderizar + renderizar sob demanda)
# ============================================================
def _run_analyze_job(job_id: str, video_path: Path, user: dict) -> None:
    storage_key = user["storage_key"]
    video_id = persistence.find_video_id(user, video_path)

    def _set_step(step: str) -> None:
        if job_id in analyze_jobs:
            analyze_jobs[job_id]["step"] = step
        log_event(stage=step, job_id=job_id, video_id=video_id,
                  user_id=user["id"], operation="analyze")

    try:
        config = load_config()
        analysis_path = default_output_path(str(video_path), output_dir=str(_user_cache_dir(storage_key)))
        run_pipeline(str(video_path), config, analysis_path, on_step=_set_step)
        candidates = get_candidates_for_review(analysis_path)
        analyze_jobs[job_id].update({
            "status": "done", "analysis_path": analysis_path,
            "video_url": _to_vod_url(str(video_path)), "candidates": candidates,
        })
    except PipelineError as e:
        analyze_jobs[job_id].update({"status": "error", "error": str(e)})
        log_event(stage="analise_falhou", status="error", job_id=job_id,
                  video_id=video_id, user_id=user["id"], error=str(e))
    except Exception:
        print(f"[ClipRadar] Erro inesperado na análise {job_id}:\n{traceback.format_exc()}")
        analyze_jobs[job_id].update({"status": "error", "error": "Erro interno inesperado durante a análise."})
        log_event(stage="analise_falhou", status="error", job_id=job_id,
                  video_id=video_id, user_id=user["id"], error="erro interno")
    finally:
        _release_job_slot()


@app.post("/api/analyze")
def start_analyze(req: AnalyzeRequest, user: dict = Depends(get_current_user)) -> dict:
    _cleanup_old_jobs()
    video_path = _resolve_vod_path(req.video_name, user["storage_key"])

    if not _try_acquire_job_slot():
        raise HTTPException(429, f"Já tem {MAX_CONCURRENT_JOBS} vídeo(s) sendo processado(s). Tente depois.")

    job_id = str(uuid.uuid4())
    analyze_jobs[job_id] = {
        "status": "running", "step": "queued", "user_id": user["id"],
        "video_id": persistence.find_video_id(user, video_path),
        "created_at": time.time(),
    }
    thread = threading.Thread(
        target=_run_analyze_job, args=(job_id, video_path, user), daemon=True
    )
    thread.start()
    return {"job_id": job_id}


@app.get("/api/analyze-status/{job_id}")
def analyze_status(job_id: str, user: dict = Depends(get_current_user)) -> dict:
    return _check_job_owner(analyze_jobs, job_id, user["id"])


@app.post("/api/render-clip")
def render_clip(req: RenderClipRequest, user: dict = Depends(get_current_user)) -> dict:
    analysis_path = _resolve_analysis_path(req.analysis_path, user["storage_key"])
    config = load_config()
    try:
        result = render_single_clip(
            analysis_path=str(analysis_path), clip_id=req.clip_id,
            start_override=req.start_seconds, end_override=req.end_seconds,
            orientation=req.orientation, burn_captions=req.burn_captions,
            subtitle_style=req.subtitle_style, preset=req.preset, layout=req.layout,
            ai_title_config=config.get("ai_title", {}),
            output_dir=str(_user_clips_dir(user["storage_key"])),
        )
    except MontageError as e:
        raise HTTPException(400, str(e))
    except Exception:
        print(f"[ClipRadar] Erro inesperado ao renderizar clip:\n{traceback.format_exc()}")
        raise HTTPException(500, "Erro interno inesperado ao renderizar.")

    persistence.record_single_clip(
        user_id=user["id"],
        storage_path=str(result["video_path"]),
        clip_identifier=req.clip_id,
        thumbnail_path=str(result["thumbnail_path"]) if result.get("thumbnail_path") else None,
        duration_seconds=result.get("duration_seconds"),
        mode="manual",
    )

    return {
        "video": _to_url(result["video_path"]),
        "thumbnail": _to_url(result["thumbnail_path"]),
        "duration_seconds": result.get("duration_seconds"),
    }
