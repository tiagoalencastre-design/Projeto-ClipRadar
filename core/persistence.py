"""
Ligação entre o fluxo real e o banco — Fase 1 (confiabilidade).

O PROBLEMA: as tabelas videos/jobs/clips existiam desde a Fase 2 da
arquitetura, mas ninguém escrevia nelas durante o uso real. O histórico do
usuário vivia no disco e na memória; um restart apagava tudo.

O QUE ESTE MÓDULO FAZ: concentra num lugar só as gravações que o
api_server.py precisa fazer. O api_server chama funções com nome óbvio
(`register_video`, `record_generated_clips`) em vez de montar SQL.

REGRA QUE VALE PRA TUDO AQUI:
    Gravar histórico NUNCA pode derrubar o processamento de vídeo. Toda
    função é tolerante a falha: se o banco estiver fora, ela avisa no log e
    devolve None. O clipe do usuário continua sendo gerado.
"""
from __future__ import annotations

from pathlib import Path

from core.observability import log_event
from core.repositories import ClipRepository, JobRepository, VideoRepository


def register_video(
    user: dict,
    file_path: str | Path,
    source_type: str = "upload",
    source_url: str | None = None,
    duration_seconds: float | None = None,
) -> int | None:
    """
    Registra um vídeo recém-chegado (upload ou download do YouTube).

    Se o mesmo caminho já estiver registrado, devolve o id existente em vez
    de duplicar — o usuário pode reenviar o mesmo arquivo.
    """
    path_str = str(file_path)
    existing = VideoRepository.find_by_storage_path(user["id"], path_str)
    if existing:
        return existing.id

    video_id = VideoRepository.create(
        user_id=user["id"],
        original_filename=Path(path_str).name,
        storage_path=path_str,
        duration_seconds=duration_seconds,
        source_type=source_type,
        source_url=source_url,
    )
    log_event(
        stage="video_registrado",
        status="ok" if video_id else "error",
        video_id=video_id,
        user_id=user["id"],
        operation=source_type,
    )
    return video_id


def find_video_id(user: dict, file_path: str | Path) -> int | None:
    """Descobre o id de um vídeo já registrado. None se não estiver no banco
    (ex: arquivo que já estava na pasta antes desta fase existir)."""
    video = VideoRepository.find_by_storage_path(user["id"], str(file_path))
    return video.id if video else None


def record_generated_clips(
    user_id: int,
    job_id: str,
    clips: list[dict],
    video_id: int | None = None,
    mode: str | None = None,
) -> int:
    """
    Registra os clipes produzidos por um job. Devolve quantos foram gravados.

    `clips` é a lista que o montage.py já devolve — cada item tem
    video_path, thumbnail_path, score, duration_seconds e clip_id.
    """
    saved = 0
    for clip in clips:
        clip_id = ClipRepository.create(
            user_id=user_id,
            storage_path=str(clip.get("video_path") or clip.get("path") or ""),
            video_id=video_id,
            job_id=job_id,
            clip_identifier=clip.get("clip_id"),
            thumbnail_path=str(clip["thumbnail_path"]) if clip.get("thumbnail_path") else None,
            score=clip.get("score"),
            duration_seconds=clip.get("duration_seconds"),
            mode=mode,
        )
        if clip_id:
            saved += 1

    log_event(
        stage="clipes_registrados",
        job_id=job_id,
        video_id=video_id,
        user_id=user_id,
        operation=mode,
        saved=saved,
        requested=len(clips),
    )
    return saved


def record_single_clip(
    user_id: int,
    storage_path: str,
    video_id: int | None = None,
    job_id: str | None = None,
    clip_identifier: str | None = None,
    thumbnail_path: str | None = None,
    score: float | None = None,
    duration_seconds: float | None = None,
    mode: str | None = "manual",
) -> int | None:
    """Registra um clipe renderizado sozinho, pela tela de revisão manual."""
    new_id = ClipRepository.create(
        user_id=user_id, storage_path=storage_path, video_id=video_id,
        job_id=job_id, clip_identifier=clip_identifier,
        thumbnail_path=thumbnail_path, score=score,
        duration_seconds=duration_seconds, mode=mode,
    )
    log_event(
        stage="clipe_registrado",
        status="ok" if new_id else "error",
        video_id=video_id, user_id=user_id, operation=mode,
    )
    return new_id


def mark_orphan_jobs_as_interrupted() -> int:
    """
    Roda uma vez no boot do servidor.

    Como o estado de execução vive na memória, qualquer job que estava
    'queued' ou 'running' quando o processo morreu não vai voltar sozinho.
    Marcamos como 'interrupted' pra que o usuário VEJA que aconteceu, em vez
    do processamento simplesmente sumir da tela.

    Devolve quantos jobs foram marcados.
    """
    count = 0
    try:
        from core import database
        with database.get_db() as conn:
            rows = conn.execute(
                "SELECT id FROM jobs WHERE status IN ('queued', 'running')"
            ).fetchall()
            for row in rows:
                JobRepository.update_status(
                    row["id"], "interrupted",
                    error="O servidor foi reiniciado durante este processamento.",
                )
                count += 1
    except Exception as e:
        log_event(stage="recuperacao_de_jobs", status="error", error=str(e))
        return 0

    if count:
        log_event(stage="recuperacao_de_jobs", interrupted=count)
    return count


def list_user_history(user_id: int, limit: int = 50) -> dict:
    """Histórico persistido do usuário — sobrevive a restart."""
    return {
        "videos": [
            {
                "id": v.id, "filename": v.original_filename,
                "source_type": v.source_type, "created_at": v.created_at,
                "duration_seconds": v.duration_seconds,
            }
            for v in VideoRepository.list_for_user(user_id)
        ],
        "jobs": [
            {
                "id": j.id, "type": j.job_type, "status": j.status,
                "step": j.step, "error": j.error,
                "started_at": j.started_at, "finished_at": j.finished_at,
                "interrupted": j.status == "interrupted",
            }
            for j in JobRepository.list_for_user(user_id, limit=limit)
        ],
        "clips": [
            {
                "id": c.id, "clip_id": c.clip_identifier, "score": c.score,
                "duration_seconds": c.duration_seconds, "mode": c.mode,
                "created_at": c.created_at, "job_id": c.job_id,
            }
            for c in ClipRepository.list_for_user(user_id)
        ],
    }
