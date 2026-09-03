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


# ============================================================
# V2 — assinatura de conteúdo e diversidade temporal
# ============================================================

def content_signature(candidate) -> dict:
    """
    Identidade de conteúdo de um candidato (§19).

    Junta região temporal, categoria, payoff e vocabulário. Dois candidatos
    com a mesma assinatura cobrem o mesmo acontecimento — mesmo que os
    recortes tenham durações diferentes.
    """
    return {
        "category": getattr(candidate, "category", "unknown"),
        "payoff_bucket": round(getattr(candidate, "payoff_seconds", 0.0) / 5.0),
        "tokens": _tokens(getattr(candidate, "transcript", "")),
        "start": getattr(candidate, "start_seconds", 0.0),
        "end": getattr(candidate, "end_seconds", 0.0),
    }


def same_content(a, b, text_threshold: float = 0.75) -> tuple[bool, str]:
    """
    Dois candidatos são o mesmo acontecimento?

    IMPORTANTE (§19): dois candidatos da MESMA história podem coexistir se
    forem propostas editoriais realmente diferentes. Por isso o mesmo payoff
    só descarta quando os recortes também são parecidos em tamanho — um
    FULL_STORY de 40s e um PAYOFF_REACTION de 12s são leituras distintas.
    """
    sa, sb = content_signature(a), content_signature(b)

    overlap = time_overlap(sa["start"], sa["end"], sb["start"], sb["end"])
    if overlap < 0.2:
        return False, ""

    if sa["payoff_bucket"] == sb["payoff_bucket"] and sa["category"] == sb["category"]:
        longer = max(a.duration_seconds, b.duration_seconds)
        shorter = min(a.duration_seconds, b.duration_seconds)
        if shorter / max(longer, 0.1) > 0.65:
            return True, "mesmo payoff e recorte parecido"

    if sa["tokens"] and sb["tokens"]:
        similarity = len(sa["tokens"] & sb["tokens"]) / len(sa["tokens"] | sb["tokens"])
        if similarity >= text_threshold and overlap >= 0.5:
            return True, f"mesma fala ({similarity:.0%})"

    # Contido não é duplicado. Um PAYOFF_REACTION de 12s vive inteiro dentro
    # de um FULL_STORY de 40s — a sobreposição é 100%, mas as propostas
    # editoriais são diferentes (§19). Só é duplicata quando os recortes
    # também têm tamanho parecido.
    longer = max(a.duration_seconds, b.duration_seconds)
    shorter = min(a.duration_seconds, b.duration_seconds)
    similar_length = shorter / max(longer, 0.1) > 0.7
    if overlap >= 0.9 and similar_length:
        return True, "cobre praticamente o mesmo trecho"

    return False, ""


def deduplicate_candidates(candidates: list, text_threshold: float = 0.75) -> list:
    """Mantém o de maior nota em cada grupo de candidatos equivalentes."""
    ordered = sorted(
        candidates,
        key=lambda c: c.heuristic_scores.get("overall", 0),
        reverse=True,
    )
    kept: list = []
    for candidate in ordered:
        duplicate = False
        for existing in kept:
            duplicate, reason = same_content(candidate, existing, text_threshold)
            if duplicate:
                candidate.selection_reason = f"descartado: {reason}"
                break
        if not duplicate:
            kept.append(candidate)
    return kept


def select_with_diversity(
    candidates: list,
    max_clips: int,
    category_weight: float = 0.35,
    temporal_weight: float = 0.2,
    temporal_window: float = 120.0,
) -> list:
    """
    Seleção final equilibrando nota, variedade de categoria e espalhamento
    no tempo (§20).

    A diversidade é FATOR, não regra: um VOD pode legitimamente render
    vários clipes do mesmo tipo se forem excelentes — a penalidade desloca
    o ranking, não proíbe.
    """
    remaining = list(candidates)
    selected: list = []
    used_categories: dict[str, int] = {}

    while remaining and len(selected) < max_clips:
        best, best_value = None, None
        for c in remaining:
            base = c.heuristic_scores.get("overall", 0)
            repeats = used_categories.get(c.category, 0)
            category_penalty = category_weight * base * (1 - 1 / (1 + repeats))

            # Penaliza clipes colados no tempo a algo já escolhido.
            near = sum(
                1 for s in selected
                if abs(s.start_seconds - c.start_seconds) < temporal_window
            )
            temporal_penalty = temporal_weight * base * (1 - 1 / (1 + near))

            value = base - category_penalty - temporal_penalty
            if best_value is None or value > best_value:
                best, best_value = c, value

        best.selected = True
        best.selection_reason = (
            f"nota {best.heuristic_scores.get('overall', 0)}, "
            f"tipo {best.candidate_type}, categoria {best.category}"
        )
        selected.append(best)
        used_categories[best.category] = used_categories.get(best.category, 0) + 1
        remaining.remove(best)

    selected.sort(key=lambda c: c.start_seconds)
    return selected
