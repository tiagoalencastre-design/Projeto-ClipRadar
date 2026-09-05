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
import subprocess
import time
import traceback
import uuid
from pathlib import Path
from typing import Literal

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response, UploadFile, File
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
from core.files import resolve_user_file, serve_file
from core.url_policy import UrlNotAllowed, validate_download_url
from core.routers import auth as auth_router
from core.routers import system as system_router
from core import persistence, retention
from core.observability import StageTimer, log_event
from datetime import datetime, timezone

from core.queue import get_queue
from core.plans import (
    UsageStatus, describe_plans, days_until_expiry, get_plan, region_for_country,
)
from core.repositories import (
    REJECTION_REASONS, ClipRepository, FeedbackRepository, UsageRepository,
    VideoRepository,
)

# As pastas vêm de core/paths.py, que também as cria no import.
#
# Estavam declaradas aqui TAMBÉM. Duas constantes com o mesmo nome em dois
# módulos é pior que duplicar função: os helpers de caminho usavam as de
# paths.py e as rotas usavam as daqui. Enquanto os valores coincidiram,
# ninguém notou — bastaria alguém mudar um dos dois para os arquivos irem
# parar em pastas diferentes.
from core.paths import (  # noqa: E402
    ASSETS_DIR, CACHE_DIR, CLIPS_DIR, FRONTEND_DIR, VODS_DIR,
)

init_db()  # cria as tabelas de usuário/sessão se ainda não existirem

# FASE 1 (confiabilidade): o estado de execução vive na memória, então jobs
# que estavam rodando quando o processo morreu não voltam sozinhos. Em vez
# de sumirem da tela, ficam marcados como 'interrupted' — o usuário vê o
# que aconteceu.
persistence.mark_orphan_jobs_as_interrupted()

# Limpeza dos clipes vencidos (7 dias no grátis, 30 no Pro). Roda em thread
# de fundo, a primeira vez 5 minutos após o boot pra não atrasar a subida.
retention.start_scheduler(CLIPS_DIR)

# Fase 1: mostra claramente em que modo o servidor está subindo — sem isso,
# é fácil esquecer se IA está de fato bloqueada ou não nesta sessão.
_app_config = get_app_config()
print(f"[ClipRadar] Modo atual: {_app_config.mode.upper()}")
print(f"[ClipRadar] Feature flags: {_app_config.as_dict()['flags']}")

app = FastAPI(title="ClipRadar API")
# /assets é público de propósito: CSS, JS e logo, servidos antes do login.
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

# Clipes e vídeos NÃO são servidos por StaticFiles.
#
# StaticFiles não passa por autenticação: bastava saber o caminho para
# baixar o arquivo de qualquer usuário, sem sessão. As rotas autenticadas
# abaixo mantêm as MESMAS URLs (/files/clips/..., /files/vods/...), então o
# front-end e os links já gerados continuam funcionando.


@app.get("/files/clips/{file_path:path}")
def serve_clip(file_path: str, request: Request, user: dict = Depends(get_current_user)):
    """Clipe gerado. Só o dono baixa."""
    path = resolve_user_file(CLIPS_DIR, user["storage_key"], file_path)
    return serve_file(path, request)


@app.get("/files/vods/{file_path:path}")
def serve_vod(file_path: str, request: Request, user: dict = Depends(get_current_user)):
    """Vídeo de origem. Só o dono baixa."""
    path = resolve_user_file(VODS_DIR, user["storage_key"], file_path)
    return serve_file(path, request)

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
    layout: Literal[
        "gameplay_full", "gameplay_facecam", "facecam_focus", "blur_background"
    ] = "gameplay_facecam"


# ---------- Autenticação ----------
# FASE 6: get_current_user, SESSION_COOKIE_NAME e APP_BASE_URL agora moram
# em core/dependencies.py, compartilhados entre api_server.py e os routers.


# ---------- Helpers de arquivo ----------
# Implementados em core/paths.py. Estavam duplicados aqui — oito funções
# com o mesmo nome e (quase) o mesmo corpo em dois arquivos. Duas cópias de
# uma regra de segurança é o pior tipo de duplicata: corrige-se uma e a
# outra continua vulnerável.
#
# Os prefixos com "_" são mantidos porque dezenas de chamadas e testes já
# usam esses nomes.
from core.paths import (  # noqa: E402
    resolve_analysis_path as _resolve_analysis_path,
    resolve_vod_path as _resolve_vod_path,
    safe_filename as _safe_filename,
    to_url as _to_url,
    to_vod_url as _to_vod_url,
    user_cache_dir as _user_cache_dir,
    user_clips_dir as _user_clips_dir,
    user_vods_dir as _user_vods_dir,
)


def _cleanup_old_jobs() -> None:
    cutoff = time.time() - JOB_EXPIRY_SECONDS
    for store in (jobs, download_jobs, analyze_jobs):
        expired = [jid for jid, data in store.items() if data.get("created_at", time.time()) < cutoff]
        for jid in expired:
            del store[jid]


# O controle de vagas vive em core/queue.py.
#
# Antes havia DUAS arquiteturas: a fila oficial (JobQueue/ThreadQueue) e um
# contador próprio aqui, com threading.Thread solto. Duas fontes de verdade
# para a mesma coisa. Agora o servidor usa só a fila — e trocar por Redis ou
# Celery no futuro é implementar JobQueue, sem tocar em nenhuma rota.
#
# A fila também cuida da vaga extra do plano Studio (priority=True) e libera
# a vaga mesmo quando o job levanta exceção.


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


class ClipFeedbackRequest(BaseModel):
    verdict: Literal["approved", "rejected"]
    clip_id: str | None = None
    job_id: str | None = None
    reason: str | None = None
    score: float | None = None
    category: str | None = None
    candidate_type: str | None = None
    duration_seconds: float | None = None
    signals: dict | None = None


def _video_minutes(video_path: Path) -> float:
    """Duração do vídeo em minutos, via ffprobe. 0.0 se não der pra ler —
    nesse caso não bloqueamos: melhor deixar passar do que recusar um vídeo
    válido por falha nossa."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip()) / 60.0
    except (subprocess.SubprocessError, ValueError, OSError):
        return 0.0


# Serializa "checar cota" + "reservar cota".
#
# Sem este lock, dois envios simultâneos leem a mesma cota livre, ambos
# passam, e o usuário processa o dobro do plano. A checagem e a reserva
# precisam ser um passo só.
_quota_lock = threading.Lock()


def _enforce_quota(user: dict, video_path: Path, job_id: str) -> float:
    """
    Verifica a cota e RESERVA os minutos do vídeo, de forma atômica.

    Recusa antes de processar: descobrir que a cota acabou depois de esperar
    20 minutos seria péssimo.

    Devolve os minutos reservados (0.0 quando não foi possível medir a
    duração — nesse caso não bloqueamos nem cobramos, porque a falha é
    nossa, não do usuário).
    """
    minutes = _video_minutes(video_path)
    if minutes <= 0:
        return 0.0

    with _quota_lock:
        allowed, message = _usage_status(user).can_process(minutes)
        if not allowed:
            raise HTTPException(402, message)
        persistence.reserve_usage(
            user_id=user["id"], job_id=job_id, minutes=minutes,
            video_id=persistence.find_video_id(user, video_path),
        )
    return minutes


def _usage_status(user: dict) -> UsageStatus:
    """Quanto o usuário já processou neste mês, e o que o plano dele permite."""
    return UsageStatus(
        plan=get_plan(user.get("plan")),
        minutes_used=UsageRepository.minutes_this_month(user["id"]),
        region=user.get("region") or "US",
    )


BRAND_KIT_DIR = Path("data/brand_kits")
BRAND_KIT_DIR.mkdir(parents=True, exist_ok=True)
MAX_LOGO_BYTES = 3 * 1024 * 1024


def brand_kit_path(user: dict) -> Path | None:
    """Logo do canal, se o plano permitir E o arquivo existir."""
    if not get_plan(user.get("plan")).brand_kit:
        return None
    path = BRAND_KIT_DIR / f"{user['storage_key']}.png"
    return path if path.exists() else None


@app.post("/api/brand-kit")
async def upload_brand_kit(
    file: UploadFile = File(...), user: dict = Depends(get_current_user)
) -> dict:
    """
    Envia a logo do canal, que substitui a marca do ClipRadar nos clipes.

    Exclusivo do plano Studio. Converte pra PNG com transparência: o
    FFmpeg precisa de canal alfa pra sobrepor sem fundo quadrado.
    """
    plan = get_plan(user.get("plan"))
    if not plan.brand_kit:
        raise HTTPException(
            402, "O Brand Kit faz parte do plano Studio. Assine pra usar sua própria logo."
        )

    content = await file.read(MAX_LOGO_BYTES + 1)
    if len(content) > MAX_LOGO_BYTES:
        raise HTTPException(413, "A logo precisa ter no máximo 3 MB.")

    try:
        from PIL import Image
        import io

        image = Image.open(io.BytesIO(content))
        image = image.convert("RGBA")
        # Limita o tamanho: logo gigante vira marca gigante no clipe.
        image.thumbnail((1000, 1000))
        image.save(BRAND_KIT_DIR / f"{user['storage_key']}.png")
    except Exception:
        raise HTTPException(400, "Não consegui ler essa imagem. Use PNG, JPG ou WEBP.")

    log_event(stage="brand_kit", operation="upload", user_id=user["id"])
    return {"ok": True}


@app.delete("/api/brand-kit")
def remove_brand_kit(user: dict = Depends(get_current_user)) -> dict:
    """Remove a logo — os clipes voltam a sair sem marca (planos pagos)."""
    path = BRAND_KIT_DIR / f"{user['storage_key']}.png"
    if path.exists():
        path.unlink()
    return {"ok": True}


@app.get("/api/plans")
def list_plans(country: str | None = None) -> dict:
    """
    Tabela de planos, já na moeda da região.

    Público de propósito: a landing page precisa mostrar preço sem login.
    O preço é definido por poder de compra local, não por conversão do
    dólar — R$ 34,90 não é "$9,90 convertido".
    """
    region = region_for_country(country)
    return {"region": region, "plans": describe_plans(region)}


@app.get("/api/usage")
def current_usage(user: dict = Depends(get_current_user)) -> dict:
    """Consumo do mês e limites do plano atual."""
    return _usage_status(user).as_dict()


@app.post("/api/clips/feedback")
def clip_feedback(req: ClipFeedbackRequest, user: dict = Depends(get_current_user)) -> dict:
    """
    Registra se o criador aprovaria ou rejeitaria um clipe.

    POR QUE ISTO EXISTE: os botões de aprovar/rejeitar já existiam na tela,
    mas só mudavam a cor. O dado se perdia. Cada voto aqui guarda também os
    SINAIS que o sistema usou pra escolher aquele momento — assim dá pra
    comparar o que o algoritmo achou com o que a pessoa achou, e ajustar os
    pesos com base em resultado real.

    Motivo de rejeição é opcional e vem de uma lista fechada: texto livre
    quase ninguém preenche, e o que se preenche não dá pra agregar.
    """
    if req.reason and req.reason not in REJECTION_REASONS:
        raise HTTPException(400, f"Motivo inválido. Use um de: {', '.join(REJECTION_REASONS)}")

    feedback_id = FeedbackRepository.record(
        user_id=user["id"], verdict=req.verdict, job_id=req.job_id,
        clip_identifier=req.clip_id, reason=req.reason, score=req.score,
        category=req.category, candidate_type=req.candidate_type,
        duration_seconds=req.duration_seconds,
        signals=json.dumps(req.signals, ensure_ascii=False) if req.signals else None,
    )
    log_event(
        stage="feedback_do_clipe", job_id=req.job_id, user_id=user["id"],
        operation=req.verdict, reason=req.reason,
    )
    return {"ok": feedback_id is not None, "id": feedback_id}


@app.get("/api/clips/feedback/summary")
def clip_feedback_summary(user: dict = Depends(get_current_user)) -> dict:
    """
    Quantos dos clipes gerados o criador realmente aprovaria, e por que
    rejeitou os outros. É a métrica de qualidade do produto.
    """
    return {
        "summary": FeedbackRepository.summary(user["id"]),
        "reasons": REJECTION_REASONS,
    }


@app.get("/api/clips")
def list_clips(user: dict = Depends(get_current_user)) -> dict:
    """
    Biblioteca de clipes — tudo que o usuário já gerou, sobrevive a restart.

    FONTE DUPLA, de propósito:
      - o BANCO tem os metadados (nota, duração, modo, data);
      - o DISCO é a verdade sobre o arquivo existir.

    Clipes gerados antes da persistência existir só estão no disco. Em vez
    de escondê-los, eles aparecem sem metadados. E um registro do banco cujo
    arquivo foi apagado à mão NÃO é listado — vídeo fantasma que não abre é
    pior que nenhum vídeo.
    """
    clips_dir = _user_clips_dir(user["storage_key"])

    known = {}
    for clip in ClipRepository.list_for_user(user["id"]):
        if not clip.storage_path:
            continue
        known[Path(clip.storage_path).name] = clip

    items = []
    for path in sorted(clips_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True):
        record = known.get(path.name)
        thumbnail = path.with_suffix(".jpg")
        items.append({
            "filename": path.name,
            "video": _to_url(str(path)),
            "thumbnail": _to_url(str(thumbnail)) if thumbnail.exists() else None,
            "size_bytes": path.stat().st_size,
            "created_at": (
                record.created_at if record
                else datetime.fromtimestamp(path.stat().st_mtime).isoformat()
            ),
            "clip_id": record.clip_identifier if record else None,
            "score": record.score if record else None,
            "duration_seconds": record.duration_seconds if record else None,
            "mode": record.mode if record else None,
            "in_database": record is not None,
            # Avisar antes de apagar. Sumir sem aviso é o que gera raiva —
            # e foi exatamente o susto que motivou a Biblioteca de Clips.
            "expires_in_days": _expiry_days(record, path, user),
        })

    return {
        "clips": items,
        "total": len(items),
        "retention_days": get_plan(user.get("plan")).retention_days,
    }


def _expiry_days(record, path: Path, user: dict) -> int:
    """Dias até o clipe deixar de ficar disponível, pelo plano do usuário."""
    try:
        created = (
            datetime.fromisoformat(record.created_at) if record
            else datetime.fromtimestamp(path.stat().st_mtime)
        )
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return days_until_expiry(created, user.get("plan"))
    except (ValueError, OSError):
        return get_plan(user.get("plan")).retention_days


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

    # Lista de PERMISSÕES, não de bloqueios. O yt-dlp aceita quase qualquer
    # URL — inclusive file:// e endereços da rede interna —, o que faria o
    # servidor buscar recursos em nome de quem pediu.
    try:
        url = validate_download_url(req.url)
    except UrlNotAllowed as e:
        raise HTTPException(400, str(e))

    job_id = str(uuid.uuid4())
    download_jobs[job_id] = {"status": "running", "user_id": user["id"], "created_at": time.time()}
    # Download também passa pela fila. É I/O de rede, não CPU, mas ocupa
    # disco e banda — e manter tudo num lugar só evita a dívida de ter dois
    # mecanismos concorrentes de novo.
    if not get_queue().submit(_run_youtube_download, job_id, url, user):
        download_jobs[job_id].update({"status": "error", "error": "Fila cheia. Tente de novo."})
        raise HTTPException(429, "Fila cheia. Tente de novo em instantes.")
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
    # Marca d'água: obrigatória no grátis, e no Studio a logo do canal
    # substitui a do ClipRadar quando enviada.
    plan = get_plan(user.get("plan"))
    brand_logo = brand_kit_path(user)
    use_watermark = plan.watermark or brand_logo is not None
    watermark_file = str(brand_logo) if brand_logo else None
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
                watermark=use_watermark, watermark_path=watermark_file,
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
                watermark=use_watermark, watermark_path=watermark_file,
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
        # Falha antes de entregar clipe nenhum: a cota volta. Sem isto, um
        # erro de FFmpeg no primeiro segundo consumiria a hora inteira.
        persistence.refund_usage(job_id)
        log_event(stage="job_falhou", status="error", job_id=job_id,
                  video_id=video_id, user_id=user["id"], error=str(e))
    except Exception:
        print(f"[ClipRadar] Erro inesperado no job {job_id}:\n{traceback.format_exc()}")
        jobs[job_id].update({"status": "error", "error": "Erro interno inesperado. Tente novamente."})
        persistence.refund_usage(job_id)
        log_event(stage="job_falhou", status="error", job_id=job_id,
                  video_id=video_id, user_id=user["id"], error="erro interno")
    # A vaga é liberada pela fila (ThreadQueue faz isso no finally dela),
    # inclusive quando esta função levanta exceção.


@app.post("/api/generate")
def generate(req: GenerateRequest, user: dict = Depends(get_current_user)) -> dict:
    _cleanup_old_jobs()
    video_path = _resolve_vod_path(req.video_name, user["storage_key"])
    # O job_id é a chave de idempotência da reserva de cota: é ele que
    # impede um retry de cobrar duas vezes.
    job_id = str(uuid.uuid4())

    plan = get_plan(user.get("plan"))
    queue = get_queue()
    # Checagem barata antes de criar qualquer registro: devolve 429 rápido
    # quando a fila já está cheia.
    if not queue.has_capacity(priority=plan.priority_queue):
        raise HTTPException(429, f"Já tem {MAX_CONCURRENT_JOBS} vídeo(s) sendo processado(s). Tente depois.")

    # ORDEM IMPORTA: o registro do job precisa existir ANTES da reserva de
    # cota, porque usage_events.job_id tem FOREIGN KEY para jobs(id). Com o
    # PRAGMA foreign_keys ligado, reservar antes falha silenciosamente e o
    # consumo não é contabilizado.
    #
    # video_id vai no dicionário: o PersistentJobStore grava tudo na tabela
    # jobs, ligando o processamento ao vídeo de origem.
    jobs[job_id] = {
        "status": "running", "step": "queued", "user_id": user["id"],
        "video_id": persistence.find_video_id(user, video_path),
        "created_at": time.time(),
    }

    try:
        _enforce_quota(user, video_path, job_id)
    except HTTPException:
        # Cota estourada: desfaz o que já foi criado antes de recusar.
        jobs[job_id].update({"status": "error", "error": "Cota mensal esgotada."})
        raise

    accepted = queue.submit(
        _run_job, job_id, video_path, user, req.mode, req.orientation,
        req.platform, req.burn_captions, req.subtitle_style, req.preset,
        priority=plan.priority_queue,
    )
    if not accepted:
        # Corrida perdida: entre a checagem e o envio, a fila encheu.
        # Desfaz tudo — o processamento não vai acontecer.
        persistence.refund_usage(job_id)
        jobs[job_id].update({"status": "error", "error": "Fila cheia. Tente de novo."})
        raise HTTPException(429, f"Já tem {MAX_CONCURRENT_JOBS} vídeo(s) sendo processado(s). Tente depois.")
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
        persistence.refund_usage(job_id)
        log_event(stage="analise_falhou", status="error", job_id=job_id,
                  video_id=video_id, user_id=user["id"], error=str(e))
    except Exception:
        print(f"[ClipRadar] Erro inesperado na análise {job_id}:\n{traceback.format_exc()}")
        analyze_jobs[job_id].update({"status": "error", "error": "Erro interno inesperado durante a análise."})
        persistence.refund_usage(job_id)
        log_event(stage="analise_falhou", status="error", job_id=job_id,
                  video_id=video_id, user_id=user["id"], error="erro interno")
    # A vaga é liberada pela fila, inclusive em caso de exceção.


@app.post("/api/analyze")
def start_analyze(req: AnalyzeRequest, user: dict = Depends(get_current_user)) -> dict:
    _cleanup_old_jobs()
    video_path = _resolve_vod_path(req.video_name, user["storage_key"])
    # O job_id nasce antes da cota: ele é a chave de idempotência da
    # reserva, e é o que impede um retry de cobrar duas vezes.
    job_id = str(uuid.uuid4())

    plan = get_plan(user.get("plan"))
    queue = get_queue()
    if not queue.has_capacity(priority=plan.priority_queue):
        raise HTTPException(429, f"Já tem {MAX_CONCURRENT_JOBS} vídeo(s) sendo processado(s). Tente depois.")

    analyze_jobs[job_id] = {
        "status": "running", "step": "queued", "user_id": user["id"],
        "video_id": persistence.find_video_id(user, video_path),
        "created_at": time.time(),
    }

    # Depois do registro do job, pela FK usage_events.job_id -> jobs(id).
    try:
        _enforce_quota(user, video_path, job_id)
    except HTTPException:
        analyze_jobs[job_id].update({"status": "error", "error": "Cota mensal esgotada."})
        raise

    accepted = queue.submit(
        _run_analyze_job, job_id, video_path, user,
        priority=plan.priority_queue,
    )
    if not accepted:
        persistence.refund_usage(job_id)
        analyze_jobs[job_id].update({"status": "error", "error": "Fila cheia. Tente de novo."})
        raise HTTPException(429, f"Já tem {MAX_CONCURRENT_JOBS} vídeo(s) sendo processado(s). Tente depois.")
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
