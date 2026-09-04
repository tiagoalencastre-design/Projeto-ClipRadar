"""
Camada de repositórios — Fase 2.

O que é isto: um lugar organizado pra ler e escrever no banco, separado por
entidade (Project, Video, Job, Clip, UsageEvent). O resto do app passa a
falar com estes repositórios em vez de montar SQL na mão.

POR QUE existe, se core/database.py já tem funções parecidas:

  1. ORGANIZAÇÃO — cada entidade tem seu repositório, com nomes previsíveis
     (get / list / create / update). Fica óbvio onde mexer.

  2. MODELS — as consultas devolvem objetos com atributos (job.status) em
     vez de linhas cruas do SQLite (row["status"]). Menos erro de digitação,
     e o editor consegue autocompletar.

  3. SEGURANÇA DE FALHA — esta é a decisão mais importante do arquivo.
     Gravar histórico NUNCA pode derrubar o processamento de vídeo. Se o
     banco estiver travado, cheio ou corrompido, o clipe do usuário ainda
     tem que ser gerado. Por isso as funções de ESCRITA usadas pelo
     pipeline nunca levantam exceção: elas avisam no console e devolvem
     None. As de LEITURA devolvem lista vazia.

     Regra prática: o banco é o histórico, não o caminho crítico.

O core/database.py continua existindo e funcionando igual — este arquivo é
construído EM CIMA dele, não no lugar dele. Nada do que já funciona muda.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Callable

from core import database


# ============================================================
# Segurança de falha
# ============================================================

def _safe(operation: str, func: Callable, fallback: Any = None) -> Any:
    """
    Roda uma operação de banco sem deixar que ela derrube o app.

    Erro de banco vira aviso no console + valor de fallback. Isso é
    proposital: perder uma linha de histórico é ruim, perder o vídeo que o
    usuário esperou 20 minutos pra processar é muito pior.
    """
    try:
        return func()
    except sqlite3.Error as e:
        print(f"[ClipRadar] Banco: falha em '{operation}' — {e}. O processamento continua.")
        return fallback


# ============================================================
# Models — objetos com atributos, em vez de linhas cruas
# ============================================================

@dataclass(frozen=True)
class Project:
    id: int
    user_id: int
    name: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Video:
    id: int
    user_id: int
    project_id: int | None
    original_filename: str
    storage_path: str
    duration_seconds: float | None
    source_type: str
    source_url: str | None
    created_at: str


@dataclass(frozen=True)
class Job:
    id: str
    user_id: int
    video_id: int | None
    job_type: str
    status: str
    step: str | None
    error: str | None
    started_at: str
    finished_at: str | None

    @property
    def is_finished(self) -> bool:
        return self.status in ("done", "error")


@dataclass(frozen=True)
class Clip:
    id: int
    user_id: int
    video_id: int | None
    job_id: str | None
    clip_identifier: str | None
    storage_path: str
    thumbnail_path: str | None
    score: float | None
    duration_seconds: float | None
    mode: str | None
    created_at: str


@dataclass(frozen=True)
class UsageEvent:
    id: int
    user_id: int
    event_type: str
    job_id: str | None
    minutes_processed: float | None
    provider: str | None
    model: str | None
    estimated_cost_usd: float | None
    created_at: str


def _to_model(model_class, row: sqlite3.Row | None):
    """
    Converte uma linha do SQLite no model correspondente.

    Só passa adiante as colunas que o model conhece — assim, se alguém
    adicionar uma coluna nova no banco, nada quebra aqui.
    """
    if row is None:
        return None
    fields = model_class.__dataclass_fields__.keys()
    data = dict(row)
    return model_class(**{k: data.get(k) for k in fields})


def _to_models(model_class, rows) -> list:
    return [_to_model(model_class, r) for r in (rows or [])]


# ============================================================
# Repositórios
# ============================================================

class ProjectRepository:
    @staticmethod
    def create(user_id: int, name: str) -> int | None:
        return _safe("criar projeto", lambda: database.create_project(user_id, name))

    @staticmethod
    def list_for_user(user_id: int) -> list[Project]:
        def _query():
            with database.get_db() as conn:
                return conn.execute(
                    "SELECT * FROM projects WHERE user_id = ? ORDER BY created_at DESC",
                    (user_id,),
                ).fetchall()
        return _to_models(Project, _safe("listar projetos", _query, []))

    @staticmethod
    def get(project_id: int, user_id: int) -> Project | None:
        """user_id é obrigatório de propósito: impede um usuário de ler
        projeto de outro por acidente."""
        def _query():
            with database.get_db() as conn:
                return conn.execute(
                    "SELECT * FROM projects WHERE id = ? AND user_id = ?",
                    (project_id, user_id),
                ).fetchone()
        return _to_model(Project, _safe("buscar projeto", _query))


class VideoRepository:
    @staticmethod
    def create(
        user_id: int, original_filename: str, storage_path: str,
        project_id: int | None = None, duration_seconds: float | None = None,
        source_type: str = "upload", source_url: str | None = None,
    ) -> int | None:
        return _safe("registrar vídeo", lambda: database.create_video(
            user_id=user_id, original_filename=original_filename,
            storage_path=storage_path, project_id=project_id,
            duration_seconds=duration_seconds, source_type=source_type,
            source_url=source_url,
        ))

    @staticmethod
    def list_for_user(user_id: int) -> list[Video]:
        return _to_models(Video, _safe(
            "listar vídeos", lambda: database.get_videos_for_user(user_id), []
        ))

    @staticmethod
    def get(video_id: int, user_id: int) -> Video | None:
        def _query():
            with database.get_db() as conn:
                return conn.execute(
                    "SELECT * FROM videos WHERE id = ? AND user_id = ?",
                    (video_id, user_id),
                ).fetchone()
        return _to_model(Video, _safe("buscar vídeo", _query))

    @staticmethod
    def find_by_storage_path(user_id: int, storage_path: str) -> Video | None:
        """Usado pra evitar registrar o mesmo arquivo duas vezes."""
        def _query():
            with database.get_db() as conn:
                return conn.execute(
                    "SELECT * FROM videos WHERE user_id = ? AND storage_path = ? "
                    "ORDER BY created_at DESC LIMIT 1",
                    (user_id, storage_path),
                ).fetchone()
        return _to_model(Video, _safe("buscar vídeo por caminho", _query))


class JobRepository:
    @staticmethod
    def create(job_id: str, user_id: int, job_type: str, video_id: int | None = None) -> bool:
        """Devolve True se gravou. False não é motivo pra parar nada."""
        result = _safe(
            "registrar job",
            lambda: (database.create_job(job_id, user_id, job_type, video_id), True)[1],
            False,
        )
        return bool(result)

    @staticmethod
    def update_status(
        job_id: str, status: str, step: str | None = None, error: str | None = None
    ) -> bool:
        result = _safe(
            "atualizar status do job",
            lambda: (database.update_job_status(job_id, status, step, error), True)[1],
            False,
        )
        return bool(result)

    @staticmethod
    def get(job_id: str) -> Job | None:
        def _query():
            with database.get_db() as conn:
                return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _to_model(Job, _safe("buscar job", _query))

    @staticmethod
    def list_for_user(user_id: int, limit: int = 50) -> list[Job]:
        def _query():
            with database.get_db() as conn:
                return conn.execute(
                    "SELECT * FROM jobs WHERE user_id = ? ORDER BY started_at DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
        return _to_models(Job, _safe("listar jobs", _query, []))

    @staticmethod
    def list_unfinished(user_id: int) -> list[Job]:
        """
        Jobs que ficaram 'queued'/'running' quando o servidor caiu.

        Hoje o estado vive em memória, então um restart perde tudo. Com isto,
        a interface pode pelo menos MOSTRAR que aquele processamento existiu
        e foi interrompido, em vez de simplesmente sumir.
        """
        def _query():
            with database.get_db() as conn:
                return conn.execute(
                    "SELECT * FROM jobs WHERE user_id = ? AND status NOT IN ('done', 'error') "
                    "ORDER BY started_at DESC",
                    (user_id,),
                ).fetchall()
        return _to_models(Job, _safe("listar jobs pendentes", _query, []))


class ClipRepository:
    @staticmethod
    def create(
        user_id: int, storage_path: str, video_id: int | None = None,
        job_id: str | None = None, clip_identifier: str | None = None,
        thumbnail_path: str | None = None, score: float | None = None,
        duration_seconds: float | None = None, mode: str | None = None,
    ) -> int | None:
        return _safe("registrar clipe", lambda: database.create_clip(
            user_id=user_id, storage_path=storage_path, video_id=video_id,
            job_id=job_id, clip_identifier=clip_identifier,
            thumbnail_path=thumbnail_path, score=score,
            duration_seconds=duration_seconds, mode=mode,
        ))

    @staticmethod
    def list_for_user(user_id: int) -> list[Clip]:
        return _to_models(Clip, _safe(
            "listar clipes", lambda: database.get_clips_for_user(user_id), []
        ))

    @staticmethod
    def list_for_job(job_id: str) -> list[Clip]:
        def _query():
            with database.get_db() as conn:
                return conn.execute(
                    "SELECT * FROM clips WHERE job_id = ? ORDER BY created_at ASC",
                    (job_id,),
                ).fetchall()
        return _to_models(Clip, _safe("listar clipes do job", _query, []))


class UsageRepository:
    @staticmethod
    def record(
        user_id: int, event_type: str, job_id: str | None = None,
        minutes_processed: float | None = None, provider: str | None = None,
        model: str | None = None, estimated_cost_usd: float | None = None,
    ) -> int | None:
        return _safe("registrar uso", lambda: database.record_usage_event(
            user_id=user_id, event_type=event_type, job_id=job_id,
            minutes_processed=minutes_processed, provider=provider,
            model=model, estimated_cost_usd=estimated_cost_usd,
        ))

    @staticmethod
    def list_for_user(user_id: int, limit: int = 100) -> list[UsageEvent]:
        def _query():
            with database.get_db() as conn:
                return conn.execute(
                    "SELECT * FROM usage_events WHERE user_id = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
        return _to_models(UsageEvent, _safe("listar uso", _query, []))

    @staticmethod
    def total_minutes(user_id: int) -> float:
        """
        Base pro futuro sistema de créditos — hoje é só leitura, ninguém
        cobra nada (flags.credits_enabled continua False).
        """
        def _query():
            with database.get_db() as conn:
                row = conn.execute(
                    "SELECT COALESCE(SUM(minutes_processed), 0) AS total "
                    "FROM usage_events WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
                return float(row["total"]) if row else 0.0
        return _safe("somar minutos", _query, 0.0)


# ============================================================
# Feedback dos criadores sobre os clipes
# ============================================================

@dataclass(frozen=True)
class ClipFeedback:
    id: int
    user_id: int
    job_id: str | None
    clip_identifier: str | None
    verdict: str
    reason: str | None
    score: float | None
    category: str | None
    candidate_type: str | None
    duration_seconds: float | None
    signals: str | None
    created_at: str


# Motivos de rejeição. São FECHADOS de propósito: campo de texto livre quase
# ninguém preenche, e o que se preenche não dá pra agregar. Cada motivo aqui
# aponta pra uma parte específica do sistema, então uma contagem alta diz
# exatamente onde mexer.
REJECTION_REASONS = {
    "bad_start": "começou no lugar errado",       # -> boundaries (hook)
    "bad_end": "terminou no lugar errado",        # -> boundaries (exit)
    "boring": "momento não é interessante",       # -> scoring/discovery
    "no_context": "não dá pra entender sozinho",  # -> standalone_score
    "bad_framing": "enquadramento ruim",          # -> layout/face_crop
    "bad_captions": "legenda errada",             # -> transcrição
    "duplicate": "repetido de outro clipe",       # -> dedup
    "other": "outro motivo",
}


class FeedbackRepository:
    @staticmethod
    def record(
        user_id: int, verdict: str, job_id: str | None = None,
        clip_identifier: str | None = None, reason: str | None = None,
        score: float | None = None, category: str | None = None,
        candidate_type: str | None = None, duration_seconds: float | None = None,
        signals: str | None = None,
    ) -> int | None:
        """
        Grava um voto. Se a pessoa mudar de ideia, o voto novo substitui o
        anterior daquele clipe — senão a contagem ficaria inflada.
        """
        def _write():
            with database.get_db() as conn:
                if clip_identifier:
                    conn.execute(
                        "DELETE FROM clip_feedback WHERE user_id = ? AND clip_identifier = ?",
                        (user_id, clip_identifier),
                    )
                cursor = conn.execute(
                    """INSERT INTO clip_feedback
                       (user_id, job_id, clip_identifier, verdict, reason, score,
                        category, candidate_type, duration_seconds, signals, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, job_id, clip_identifier, verdict, reason, score,
                     category, candidate_type, duration_seconds, signals,
                     database._now()),
                )
                conn.commit()
                return cursor.lastrowid
        return _safe("registrar feedback", _write)

    @staticmethod
    def list_for_user(user_id: int, limit: int = 500) -> list[ClipFeedback]:
        def _query():
            with database.get_db() as conn:
                return conn.execute(
                    "SELECT * FROM clip_feedback WHERE user_id = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit),
                ).fetchall()
        return _to_models(ClipFeedback, _safe("listar feedback", _query, []))

    @staticmethod
    def summary(user_id: int | None = None) -> dict:
        """
        O número que importa: de cada 10 clipes, quantos a pessoa aprovaria.

        Junto vem a contagem por motivo de rejeição — é ela que diz qual
        parte do sistema melhorar primeiro.
        """
        def _query():
            with database.get_db() as conn:
                where, params = "", ()
                if user_id is not None:
                    where, params = "WHERE user_id = ?", (user_id,)

                rows = conn.execute(
                    f"SELECT verdict, COUNT(*) AS n FROM clip_feedback {where} "
                    f"GROUP BY verdict", params
                ).fetchall()
                counts = {r["verdict"]: r["n"] for r in rows}

                reason_rows = conn.execute(
                    f"SELECT reason, COUNT(*) AS n FROM clip_feedback "
                    f"{where + (' AND' if where else 'WHERE')} verdict = 'rejected' "
                    f"AND reason IS NOT NULL GROUP BY reason ORDER BY n DESC",
                    params
                ).fetchall()

                approved = counts.get("approved", 0)
                rejected = counts.get("rejected", 0)
                total = approved + rejected
                return {
                    "approved": approved,
                    "rejected": rejected,
                    "total": total,
                    "approval_rate": round(approved / total, 3) if total else None,
                    "rejection_reasons": {r["reason"]: r["n"] for r in reason_rows},
                }
        return _safe("resumir feedback", _query, {
            "approved": 0, "rejected": 0, "total": 0,
            "approval_rate": None, "rejection_reasons": {},
        })


def _minutes_this_month(user_id: int) -> float:
    """
    Minutos de vídeo processados no mês corrente.

    A régua da cobrança é o MINUTO ENVIADO, não o clipe gerado: o custo é
    processar 1 hora de vídeo, saindo 3 ou 20 clipes dela.
    """
    def _query():
        with database.get_db() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(minutes_processed), 0) AS total "
                "FROM usage_events WHERE user_id = ? "
                "AND strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')",
                (user_id,),
            ).fetchone()
            return float(row["total"]) if row else 0.0
    return _safe("somar minutos do mês", _query, 0.0)


UsageRepository.minutes_this_month = staticmethod(_minutes_this_month)
