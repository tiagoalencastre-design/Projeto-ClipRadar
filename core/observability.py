"""
Logging estruturado — Fase 8.

HOJE: `structured=False` no app_config, então tudo continua saindo como
print() no console, igual a antes. Nada mudou no que você vê.

QUANDO LIGAR: cada evento vira uma linha JSON, pronta pra ser lida por
ferramenta de monitoramento. Os campos pedidos no plano estão todos aqui:
job_id, video_id, stage, duration, model, provider, estimated_cost, status,
error.

    from core.observability import log_event, StageTimer

    with StageTimer("transcricao", job_id="abc") as timer:
        ...
    # ao sair, registra sozinho a duração

CUSTO: `estimate_cost()` calcula o custo aproximado por tokens. A tabela é
pequena e vai ficar desatualizada — por isso `track_cost` começa desligado,
e o número é sempre uma ESTIMATIVA, nunca cobrança.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from core.app_config import get_app_config

# Custo aproximado em dólares por 1 milhão de tokens.
# Confira os valores atuais antes de usar isso pra decidir preço.
_COST_PER_MILLION = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Custo estimado em dólares. None se o modelo não estiver na tabela —
    melhor não ter número do que ter um número errado."""
    price = _COST_PER_MILLION.get(model)
    if not price:
        return None
    cost = (
        (prompt_tokens / 1_000_000) * price["input"]
        + (completion_tokens / 1_000_000) * price["output"]
    )
    return round(cost, 6)


def log_event(
    stage: str,
    status: str = "ok",
    job_id: str | None = None,
    video_id: int | None = None,
    duration_seconds: float | None = None,
    model: str | None = None,
    provider: str | None = None,
    estimated_cost_usd: float | None = None,
    error: str | None = None,
    **extra,
) -> dict:
    """
    Registra um evento. Devolve o dicionário do evento (útil pra teste e
    pra quem quiser gravar no banco também).
    """
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "status": status,
        "job_id": job_id,
        "video_id": video_id,
        "duration_seconds": round(duration_seconds, 2) if duration_seconds is not None else None,
        "model": model,
        "provider": provider,
        "estimated_cost_usd": estimated_cost_usd,
        "error": error,
    }
    event.update(extra)
    event = {k: v for k, v in event.items() if v is not None}

    if get_app_config().observability.structured:
        print(json.dumps(event, ensure_ascii=False))
    else:
        # Formato legível — é o que você já está acostumado a ver.
        parts = [f"[ClipRadar] {stage}"]
        if duration_seconds is not None:
            parts.append(f"({duration_seconds:.1f}s)")
        if status != "ok":
            parts.append(f"— {status}")
        if error:
            parts.append(f": {error}")
        print(" ".join(parts))

    return event


class StageTimer:
    """
    Mede quanto durou uma etapa e registra sozinho ao terminar.

    Registra mesmo quando dá erro — inclusive gravando qual foi o erro. A
    exceção continua subindo normalmente; isto só observa, não interfere.
    """

    def __init__(self, stage: str, **fields):
        self.stage = stage
        self.fields = fields
        self.started_at = 0.0
        self.event: dict | None = None

    def __enter__(self) -> "StageTimer":
        self.started_at = time.time()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        duration = time.time() - self.started_at
        self.event = log_event(
            stage=self.stage,
            status="error" if exc_type else "ok",
            duration_seconds=duration,
            error=str(exc_value) if exc_value else None,
            **self.fields,
        )
        return False  # nunca engole a exceção
