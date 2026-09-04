"""
Pipeline de descoberta e seleção — ClipRadar V2.

Separa explicitamente as duas perguntas (§2, §21):

    DISCOVERY  "quais acontecimentos potencialmente interessantes existem?"
    SELECTION  "quais deles merecem virar clipes?"

O sistema antigo respondia as duas ao mesmo tempo, e por isso perdia
oportunidades: descartava candidatos enquanto ainda estava descobrindo.

FLUXO:
    sinais -> eventos -> histórias -> candidatos (vários por história)
           -> avaliação editorial -> dedup -> diversidade -> clipes finais

Nenhuma IA é chamada. Tudo local e determinístico.
"""
from __future__ import annotations

from core.candidates import ClipCandidate, generate_candidates
from core.dedup import deduplicate_candidates, select_with_diversity
from core.detection import RawSignal
from core.editorial import EditorialAnalyzer, analyze_all
from core.events import build_events
from core.story import build_stories
from core.transcription import TranscriptSegment


class DiscoveryReport:
    """
    Quantos candidatos sobreviveram a cada estágio (§31).

    Serve pra responder "por que esse clipe não apareceu?" sem adivinhação.
    """

    def __init__(self):
        self.all_candidates: list = []
        self.events = 0
        self.stories = 0
        self.raw_candidates = 0
        self.trimmed_to: int | None = None
        self.auto_mode = False
        self.auto_qualified = 0
        self.below_standard = False
        self.valid_candidates = 0
        self.after_score_floor = 0
        self.after_dedup = 0
        self.final = 0
        self.per_story: list[int] = []

    def as_dict(self) -> dict:
        return {
            "events": self.events,
            "stories": self.stories,
            "raw_candidates": self.raw_candidates,
            "trimmed_to": self.trimmed_to,
            "auto_mode": self.auto_mode,
            "auto_qualified": self.auto_qualified,
            "below_standard": self.below_standard,
            "valid_candidates": self.valid_candidates,
            "after_score_floor": self.after_score_floor,
            "after_dedup": self.after_dedup,
            "final": self.final,
            "candidates_per_story": self.per_story,
        }

    def lines(self) -> list[str]:
        out = [
            f"[DISCOVERY] {self.events} eventos",
            f"[STORIES]   {self.stories} histórias",
            f"[CANDIDATES] {self.raw_candidates} candidatos "
            f"(por história: {self.per_story})"
            + (f" → {self.trimmed_to} após cota" if self.trimmed_to else ""),
            f"[VALIDATION] {self.raw_candidates} → {self.valid_candidates} válidos",
            f"[RANKING]   {self.valid_candidates} → {self.after_score_floor} acima do mínimo",
            f"[DEDUP]     {self.after_score_floor} → {self.after_dedup} únicos",
            f"[FINAL]     {self.final} clipes selecionados"
            + (f" (AUTO: {self.auto_qualified} acima do padrão)" if self.auto_mode else "")
            + (" — nenhum atingiu o padrão de qualidade" if self.below_standard else ""),
        ]
        return out


def _video_span(events: list) -> float:
    """Duração coberta pelos eventos, em segundos. Base pra cota."""
    if not events:
        return 0.0
    return max(e.end_seconds for e in events)


def _candidate_budget(video_seconds: float, discovery_cfg: dict) -> int:
    """
    Quantos candidatos brutos manter, proporcional à duração do vídeo.

    Um VOD de 10 minutos não precisa de 100 candidatos; um de 3 horas
    precisa de bem mais que isso. O teto absoluto existe só como proteção
    contra consumo de memória.
    """
    per_hour = int(discovery_cfg.get("max_candidates_per_hour", 60))
    absolute = int(discovery_cfg.get("absolute_max_candidates", 600))
    hours = max(video_seconds / 3600.0, 0.25)   # mínimo de 15 min de cota
    return max(min(int(per_hour * hours), absolute), 20)


def _trim_evenly(candidates: list, limit: int) -> list:
    """
    Corta o excesso mantendo cobertura de TODO o vídeo.

    Divide o vídeo em faixas de tempo e guarda os melhores de cada faixa.
    Cortar por nota global concentraria tudo no trecho mais barulhento e
    reintroduziria o problema que esta função existe pra evitar.
    """
    if len(candidates) <= limit:
        return candidates

    ordered = sorted(candidates, key=lambda c: c.start_seconds)
    span_start = ordered[0].start_seconds
    span_end = ordered[-1].end_seconds
    span = max(span_end - span_start, 1.0)

    buckets: dict[int, list] = {}
    bucket_count = max(min(limit, 20), 1)
    for c in ordered:
        index = min(int((c.start_seconds - span_start) / span * bucket_count), bucket_count - 1)
        buckets.setdefault(index, []).append(c)

    # Rodízio entre as faixas: pega um de cada, depois o segundo de cada...
    kept: list = []
    round_index = 0
    while len(kept) < limit:
        added = False
        for index in sorted(buckets):
            group = buckets[index]
            if round_index < len(group):
                kept.append(group[round_index])
                added = True
                if len(kept) >= limit:
                    break
        if not added:
            break
        round_index += 1
    return kept


def discover_and_select(
    signals: list[RawSignal],
    transcript: list[TranscriptSegment],
    config: dict,
    analyzer: EditorialAnalyzer | None = None,
    verbose: bool = True,
) -> tuple[list[ClipCandidate], DiscoveryReport]:
    """
    Devolve (clipes_selecionados, relatório).

    Também devolve os candidatos NÃO selecionados marcados com o motivo —
    quem quiser inspecionar tudo pode olhar o relatório.
    """
    discovery_cfg = config.get("discovery", {}) or {}
    selection_cfg = config.get("selection", {}) or {}
    duration_cfg = config.get("clip_duration", {}) or {}
    dedup_cfg = config.get("deduplication", {}) or {}
    cand_cfg = config.get("candidate_moments", {}) or {}

    report = DiscoveryReport()

    # --- DISCOVERY: permissivo de propósito ---
    events = build_events(
        signals, transcript,
        window_seconds=cand_cfg.get("event_window_seconds", 6.0),
    )
    report.events = len(events)

    stories = build_stories(
        events, transcript,
        max_silence_seconds=cand_cfg.get("story_max_silence_seconds", 4.0),
        # §9: a história é o CONTEXTO; o clipe é uma interpretação dela.
        # Uma história de 120s pode gerar candidatos de 30s, 45s e 65s — por
        # isso o limite dela é independente do limite do clipe.
        max_story_seconds=float(
            (config.get("story", {}) or {}).get("story_max_duration_seconds", 180.0)
        ),
    )
    report.stories = len(stories)

    gen_cfg = {
        "absolute_min_seconds": duration_cfg.get("absolute_min_seconds", 8.0),
        "absolute_max_seconds": duration_cfg.get("absolute_max_seconds", 75.0),
        "max_context_seconds": (config.get("context", {}) or {}).get("max_context_seconds", 45.0),
        "tail_padding_seconds": cand_cfg.get("tail_padding_seconds", 8.0),
    }

    # COTA PROPORCIONAL À DURAÇÃO, não um teto global.
    #
    # O BUG QUE ISTO CORRIGE: antes o laço parava assim que o total de
    # candidatos batia no teto. Num VOD de 3 horas, isso significava
    # analisar os primeiros 20 minutos e IGNORAR o resto — em silêncio.
    #
    # Agora o teto acompanha a duração do vídeo, e quando ele é atingido a
    # geração continua até o fim: o corte acontece depois, mantendo os
    # melhores candidatos de CADA PARTE do vídeo em vez dos primeiros que
    # apareceram.
    video_seconds = _video_span(events)
    max_raw = _candidate_budget(video_seconds, discovery_cfg)

    all_candidates: list[ClipCandidate] = []
    for story in stories:
        produced = generate_candidates(story, transcript, gen_cfg)
        report.per_story.append(len(produced))
        all_candidates.extend(produced)

    report.raw_candidates = len(all_candidates)
    if len(all_candidates) > max_raw:
        all_candidates = _trim_evenly(all_candidates, max_raw)
        report.trimmed_to = len(all_candidates)

    if not all_candidates:
        if verbose:
            for line in report.lines():
                print(line)
        return [], report

    # --- SELECTION: só agora filtramos ---
    analyze_all(
        all_candidates, analyzer,
        weights=(config.get("editorial", {}) or {}) or None,
        duration_config=duration_cfg,
    )

    # VALIDATION: descarta só o que é inutilizável (curto demais, sem
    # payoff dentro do recorte). Nada é cortado por NOTA nesta etapa —
    # notas só entram depois de todos os candidatos existirem (§8).
    min_clip = float(duration_cfg.get("absolute_min_seconds", 8.0))
    valid = []
    for c in all_candidates:
        if c.duration_seconds < max(min_clip * 0.5, 3.0):
            c.selection_reason = "curto demais pra virar clipe"
            continue
        if not (c.start_seconds <= c.payoff_seconds <= c.end_seconds):
            c.selection_reason = "o payoff ficou fora do recorte"
            continue
        valid.append(c)
    report.valid_candidates = len(valid)
    report.all_candidates = all_candidates

    min_score = float(selection_cfg.get("min_score", 40.0))
    viable = [
        c for c in valid
        if c.heuristic_scores.get("overall", 0) >= min_score
    ]
    for c in valid:
        if c not in viable:
            c.selection_reason = f"nota abaixo do mínimo ({min_score})"
    # Se NADA passou da nota mínima, não devolvemos uma tela vazia: entram
    # os melhores disponíveis, marcados como abaixo do padrão. O usuário
    # decide se aproveita — mas precisa ver o que o vídeo tinha de melhor.
    below_standard = False
    if not viable and valid:
        floor = int(selection_cfg.get("auto_min_clips", 3))
        viable = sorted(
            valid, key=lambda c: c.heuristic_scores.get("overall", 0), reverse=True
        )[:floor]
        for c in viable:
            c.selection_reason = "abaixo do padrão — melhor disponível neste vídeo"
        below_standard = True

    report.after_score_floor = len(viable)
    report.below_standard = below_standard

    unique = deduplicate_candidates(
        viable,
        text_threshold=float(dedup_cfg.get("semantic_similarity_threshold", 0.75)),
        overlap_threshold=float(dedup_cfg.get("temporal_overlap_threshold", 0.6)),
    )
    report.after_dedup = len(unique)

    # MODO AUTO (item 14): a quantidade sai da QUALIDADE disponível, não de
    # um número fixo. Um vídeo fraco não deve render 10 clipes ruins só
    # porque alguém pediu 10.
    #
    # Regra: entram os candidatos acima do padrão de excelência, respeitando
    # um teto de segurança. Se nenhum atingir o padrão, entrega os melhores
    # até o mínimo — melhor pouca coisa boa do que nada.
    requested = selection_cfg.get("max_final_clips", "auto")
    if str(requested).lower() == "auto":
        good_score = float(selection_cfg.get("auto_quality_threshold", 55.0))
        ceiling = int(selection_cfg.get("auto_max_clips", 20))
        floor = int(selection_cfg.get("auto_min_clips", 3))
        good = [c for c in unique if c.heuristic_scores.get("overall", 0) >= good_score]
        max_clips = max(min(len(good), ceiling), min(floor, len(unique)))
        report.auto_mode = True
        report.auto_qualified = len(good)
    else:
        max_clips = int(requested)

    if selection_cfg.get("diversity_enabled", True):
        final = select_with_diversity(
            unique,
            max_clips=max_clips,
            category_weight=float(selection_cfg.get("category_diversity_weight", 0.35)),
            temporal_weight=float(selection_cfg.get("temporal_diversity_weight", 0.2)),
        )
    else:
        final = sorted(
            unique, key=lambda c: c.heuristic_scores.get("overall", 0), reverse=True
        )[:max_clips]
        for c in final:
            c.selected = True
    report.final = len(final)

    if verbose:
        for line in report.lines():
            print(line)

    return final, report
