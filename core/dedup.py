"""
Deduplicação e diversidade — Rebuild do motor de clipping.

O PROBLEMA ANTIGO: `_suppress_overlapping` descartava qualquer candidato a
menos de 15 segundos de um já aceito. Puramente temporal. Uma reação
engraçada 15s depois de um clutch era APAGADA — mesmo sendo um clipe
independente e bom. Era a maior fonte de "momentos independentes
descartados" e de "poucos clips".

O QUE MUDA:

  DEDUP  — compara CONTEÚDO. Dois candidatos são redundantes se cobrem o
           mesmo acontecimento (sobreposição real de tempo) OU se dizem
           praticamente a mesma coisa (fala parecida). Estar perto no tempo,
           sozinho, não é motivo pra descartar.

  DIVERSIDADE — o ranking final não é só "top N por score". Um vídeo com 3
           clutches, 2 momentos engraçados e 1 história deve virar um
           conjunto variado, não 6 clutches. Fazemos isso penalizando
           repetição de categoria conforme a lista vai sendo montada.
"""
from __future__ import annotations

import re

# Sobreposição temporal a partir da qual dois clipes cobrem o mesmo evento.
OVERLAP_REDUNDANT = 0.6
# Semelhança de fala a partir da qual dois clipes dizem a mesma coisa.
TEXT_REDUNDANT = 0.7

_STOPWORDS = {
    "a", "o", "e", "de", "da", "do", "que", "um", "uma", "para", "pra", "com",
    "em", "no", "na", "os", "as", "eu", "você", "voce", "é", "eh", "foi", "ta",
    "tá", "mano", "cara", "the", "and", "to", "of", "it", "is", "i", "you",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-zà-ú0-9]+", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def text_similarity(a: str, b: str) -> float:
    """
    Semelhança entre duas falas (Jaccard sobre palavras relevantes).

    Palavras muito comuns são removidas: duas falas não são "parecidas" só
    porque as duas têm "que" e "para".
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def time_overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Sobreposição relativa ao MENOR dos dois trechos."""
    start, end = max(a_start, b_start), min(a_end, b_end)
    intersection = max(end - start, 0.0)
    if intersection <= 0:
        return 0.0
    smaller = min(a_end - a_start, b_end - b_start)
    return intersection / smaller if smaller > 0 else 0.0


def is_redundant(
    candidate: dict,
    kept: dict,
    overlap_threshold: float = OVERLAP_REDUNDANT,
    text_threshold: float = TEXT_REDUNDANT,
) -> tuple[bool, str]:
    """
    O candidato é redundante em relação a um clipe já aceito?

    Cada candidato é um dicionário com context_start_seconds, end_seconds e
    transcript_excerpt.
    """
    overlap = time_overlap(
        candidate["context_start_seconds"], candidate["end_seconds"],
        kept["context_start_seconds"], kept["end_seconds"],
    )
    if overlap >= overlap_threshold:
        return True, f"cobre o mesmo trecho ({overlap:.0%} de sobreposição)"

    similarity = text_similarity(
        candidate.get("transcript_excerpt", ""), kept.get("transcript_excerpt", "")
    )
    if similarity >= text_threshold and overlap > 0.15:
        return True, f"diz quase a mesma coisa ({similarity:.0%} de semelhança)"

    return False, ""


def deduplicate(moments: list[dict]) -> list[dict]:
    """
    Remove redundantes, preservando o de maior score em cada conflito.

    Diferente do sistema antigo: dois momentos podem ficar a 3 segundos um do
    outro e ambos sobreviverem, desde que cubram acontecimentos diferentes.
    """
    ordered = sorted(moments, key=lambda m: m.get("score", 0), reverse=True)
    kept: list[dict] = []
    for candidate in ordered:
        redundant = False
        for existing in kept:
            redundant, _ = is_redundant(candidate, existing)
            if redundant:
                break
        if not redundant:
            kept.append(candidate)
    return kept


def rank_with_diversity(
    moments: list[dict],
    max_clips: int,
    diversity_weight: float = 0.35,
) -> list[dict]:
    """
    Ranking que equilibra qualidade e variedade.

    A cada escolha, categorias já usadas perdem valor. O primeiro clutch
    entra pelo score cheio; o terceiro clutch compete em desvantagem contra
    um momento engraçado que ainda não apareceu.

    diversity_weight=0 devolve o ranking puro por score.
    """
    remaining = sorted(moments, key=lambda m: m.get("score", 0), reverse=True)
    selected: list[dict] = []
    used: dict[str, int] = {}

    while remaining and len(selected) < max_clips:
        best, best_value = None, None
        for m in remaining:
            category = m.get("category", "unknown")
            repeats = used.get(category, 0)
            # Penalidade decrescente: 2º da categoria sofre mais que o 5º,
            # porque o salto de "só tem um" pra "já tem dois" é o que mais
            # muda a percepção de variedade.
            penalty = diversity_weight * m.get("score", 0) * (1 - 1 / (1 + repeats))
            value = m.get("score", 0) - penalty
            if best_value is None or value > best_value:
                best, best_value = m, value

        selected.append(best)
        used[best.get("category", "unknown")] = used.get(best.get("category", "unknown"), 0) + 1
        remaining.remove(best)

    return selected
