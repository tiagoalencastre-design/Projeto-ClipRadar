"""
Limpeza de clipes vencidos.

REGRA: grátis guarda 7 dias, Pro guarda 30. Passado o prazo, o arquivo é
apagado do disco e o registro é marcado como expirado no banco.

POR QUE APAGAR: disco é o custo que mais cresce sem ninguém perceber. Um
usuário ativo gera dezenas de clipes por mês, cada um com dezenas de MB.

O CUIDADO QUE IMPORTA: a interface avisa quantos dias faltam em cada clipe
(campo expires_in_days). Apagar é aceitável; apagar sem avisar não é.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from core.observability import log_event
from core.plans import get_plan

# Margem de segurança: só apaga depois de passar do prazo com folga, pra
# nunca apagar por causa de fuso horário ou relógio desalinhado.
GRACE_HOURS = 12


def _age_in_days(path: Path) -> float:
    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return 0.0
    return (datetime.now(timezone.utc) - modified).total_seconds() / 86400


def find_expired(clips_dir: Path, plan_id: str) -> list[Path]:
    """Clipes que já passaram do prazo do plano, com a margem de segurança."""
    limit = get_plan(plan_id).retention_days + GRACE_HOURS / 24
    if not clips_dir.exists():
        return []
    return [
        path for path in clips_dir.glob("*.mp4")
        if _age_in_days(path) > limit
    ]


def cleanup_user(clips_dir: Path, plan_id: str, dry_run: bool = False) -> dict:
    """
    Apaga os clipes vencidos de um usuário.

    dry_run=True só relata o que apagaria — útil pra conferir antes de
    deixar rodando sozinho.
    """
    expired = find_expired(clips_dir, plan_id)
    removed, freed_bytes = 0, 0

    for path in expired:
        try:
            size = path.stat().st_size
            if not dry_run:
                path.unlink()
                # A miniatura acompanha o clipe.
                thumbnail = path.with_suffix(".jpg")
                if thumbnail.exists():
                    thumbnail.unlink()
            removed += 1
            freed_bytes += size
        except OSError as e:
            # Arquivo em uso ou já removido: segue adiante. Falhar a limpeza
            # inteira por causa de um arquivo seria pior.
            log_event(stage="limpeza_de_clipes", status="error", error=str(e))

    if removed:
        log_event(
            stage="limpeza_de_clipes",
            operation="dry_run" if dry_run else "removidos",
            removed=removed,
            freed_mb=round(freed_bytes / (1024 * 1024), 1),
        )
    return {
        "removed": removed,
        "freed_mb": round(freed_bytes / (1024 * 1024), 1),
        "dry_run": dry_run,
    }


# ============================================================
# Agendamento
# ============================================================

def cleanup_all_users(clips_root: Path, dry_run: bool = False) -> dict:
    """
    Varre todos os usuários e apaga o que venceu, respeitando o plano de
    cada um. Cada pasta sob clips_root é a storage_key de um usuário.
    """
    from core import database

    plans_by_key: dict[str, str] = {}
    try:
        with database.get_db() as conn:
            for row in conn.execute("SELECT storage_key, plan FROM users"):
                plans_by_key[row["storage_key"]] = row["plan"]
    except Exception as e:
        log_event(stage="limpeza_de_clipes", status="error", error=str(e))
        return {"users": 0, "removed": 0, "freed_mb": 0.0}

    removed, freed = 0, 0.0
    users = 0
    if clips_root.exists():
        for folder in clips_root.iterdir():
            if not folder.is_dir():
                continue
            users += 1
            # Pasta sem dono conhecido usa a regra do grátis (a mais curta),
            # mas nunca some sem passar da margem de segurança.
            result = cleanup_user(folder, plans_by_key.get(folder.name, "free"), dry_run)
            removed += result["removed"]
            freed += result["freed_mb"]

    return {"users": users, "removed": removed, "freed_mb": round(freed, 1)}


def start_scheduler(clips_root: Path, interval_hours: int = 24) -> None:
    """
    Roda a limpeza periodicamente numa thread de fundo.

    DECISÕES:
      - daemon=True: não impede o servidor de encerrar.
      - primeira execução após 5 minutos, não no boot: subir o servidor não
        pode ficar mais lento por causa disso.
      - qualquer erro é registrado e a thread continua viva. Uma limpeza que
        morre silenciosamente é pior que nenhuma limpeza.
    """
    import threading

    def _loop():
        time.sleep(300)   # deixa o servidor subir primeiro
        while True:
            try:
                result = cleanup_all_users(clips_root)
                if result["removed"]:
                    log_event(
                        stage="limpeza_agendada",
                        removed=result["removed"],
                        freed_mb=result["freed_mb"],
                        users=result["users"],
                    )
            except Exception as e:
                log_event(stage="limpeza_agendada", status="error", error=str(e))
            time.sleep(interval_hours * 3600)

    threading.Thread(target=_loop, daemon=True, name="retention-cleanup").start()
    log_event(stage="limpeza_agendada", operation="iniciada",
              interval_hours=interval_hours)
