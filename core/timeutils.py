"""Funções pequenas e reutilizáveis entre core/ e app/."""
from __future__ import annotations


def format_timestamp(seconds: float) -> str:
    """
    Converte segundos (float) em texto tipo 1:23:45 ou 4:07, dependendo se
    passa de 1 hora ou não. Usado em toda exibição de tempo pro usuário
    (terminal e tela de revisão) — o cálculo interno continua em segundos,
    isso é só formatação pra leitura humana.
    """
    total_seconds = int(round(seconds))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
