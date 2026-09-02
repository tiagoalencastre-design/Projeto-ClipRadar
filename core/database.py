"""
Banco de dados simples (SQLite — um arquivo só, sem precisar instalar nem
configurar nenhum servidor de banco separado) — guarda contas de usuário e
sessões de login.

Fica em data/cliparadar.db — não é versionado no Git (já está no .gitignore
junto com o resto de data/).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("data/cliparadar.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Cria as tabelas se ainda não existirem — seguro rodar toda vez que o
    servidor inicia, não apaga nada que já existe. CREATE TABLE IF NOT EXISTS
    funciona como um mecanismo de migração simples e seguro: adicionar uma
    tabela nova aqui nunca afeta as que já existem."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                storage_key TEXT UNIQUE NOT NULL,
                email_verified INTEGER NOT NULL DEFAULT 0,
                verification_token TEXT,
                verification_sent_at TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        # ---------- Fase 2: estrutura de domínio (só cria, não popula ainda) ----------

        conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                project_id INTEGER,
                original_filename TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                duration_seconds REAL,
                source_type TEXT NOT NULL DEFAULT 'upload',
                source_url TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(project_id) REFERENCES projects(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                video_id INTEGER,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                step TEXT,
                error TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(video_id) REFERENCES videos(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS clips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                video_id INTEGER,
                job_id TEXT,
                clip_identifier TEXT,
                storage_path TEXT NOT NULL,
                thumbnail_path TEXT,
                score REAL,
                duration_seconds REAL,
                mode TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(video_id) REFERENCES videos(id),
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                job_id TEXT,
                minutes_processed REAL,
                provider TEXT,
                model TEXT,
                estimated_cost_usd REAL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            )
        """)

        conn.commit()


# ============================================================
# Fase 2 — funções básicas de acesso às tabelas novas.
#
# IMPORTANTE: nada aqui é chamado pelo fluxo real do app ainda (isso é a
# Fase 4, "persistência"). Por enquanto essas funções só existem pra provar
# que a estrutura do banco funciona de verdade — testadas isoladamente.
# ============================================================

def create_project(user_id: int, name: str) -> int:
    now = _now()
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO projects (user_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (user_id, name, now, now),
        )
        conn.commit()
        return cursor.lastrowid


def create_video(
    user_id: int, original_filename: str, storage_path: str,
    project_id: int | None = None, duration_seconds: float | None = None,
    source_type: str = "upload", source_url: str | None = None,
) -> int:
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO videos
               (user_id, project_id, original_filename, storage_path, duration_seconds,
                source_type, source_url, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, project_id, original_filename, storage_path, duration_seconds,
             source_type, source_url, _now()),
        )
        conn.commit()
        return cursor.lastrowid


def create_job(job_id: str, user_id: int, job_type: str, video_id: int | None = None) -> None:
    with get_db() as conn:
        conn.execute(
            """INSERT INTO jobs (id, user_id, video_id, job_type, status, started_at)
               VALUES (?, ?, ?, ?, 'queued', ?)""",
            (job_id, user_id, video_id, job_type, _now()),
        )
        conn.commit()


def update_job_status(job_id: str, status: str, step: str | None = None, error: str | None = None) -> None:
    finished_at = _now() if status in ("done", "error") else None
    with get_db() as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, step = COALESCE(?, step), error = ?, finished_at = COALESCE(?, finished_at) WHERE id = ?",
            (status, step, error, finished_at, job_id),
        )
        conn.commit()


def create_clip(
    user_id: int, storage_path: str, video_id: int | None = None, job_id: str | None = None,
    clip_identifier: str | None = None, thumbnail_path: str | None = None,
    score: float | None = None, duration_seconds: float | None = None, mode: str | None = None,
) -> int:
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO clips
               (user_id, video_id, job_id, clip_identifier, storage_path, thumbnail_path,
                score, duration_seconds, mode, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, video_id, job_id, clip_identifier, storage_path, thumbnail_path,
             score, duration_seconds, mode, _now()),
        )
        conn.commit()
        return cursor.lastrowid


def record_usage_event(
    user_id: int, event_type: str, job_id: str | None = None,
    minutes_processed: float | None = None, provider: str | None = None,
    model: str | None = None, estimated_cost_usd: float | None = None,
) -> int:
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO usage_events
               (user_id, event_type, job_id, minutes_processed, provider, model, estimated_cost_usd, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, event_type, job_id, minutes_processed, provider, model, estimated_cost_usd, _now()),
        )
        conn.commit()
        return cursor.lastrowid


def get_videos_for_user(user_id: int) -> list[sqlite3.Row]:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM videos WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        ).fetchall()


def get_clips_for_user(user_id: int) -> list[sqlite3.Row]:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM clips WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        ).fetchall()


def get_jobs_for_user(user_id: int) -> list[sqlite3.Row]:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM jobs WHERE user_id = ? ORDER BY started_at DESC", (user_id,)
        ).fetchall()
