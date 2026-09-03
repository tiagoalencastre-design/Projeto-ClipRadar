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
            f"(por história: {self.per_story})",
            f"[VALIDATION] {self.raw_candidates} → {self.valid_candidates} válidos",
            f"[RANKING]   {self.valid_candidates} → {self.after_score_floor} acima do mínimo",
            f"[DEDUP]     {self.after_score_floor} → {self.after_dedup} únicos",
            f"[FINAL]     {self.final} clipes selecionados",
        ]
        return out


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

    all_candidates: list[ClipCandidate] = []
    max_raw = int(discovery_cfg.get("max_raw_candidates", 100))
    for story in stories:
        produced = generate_candidates(story, transcript, gen_cfg)
        report.per_story.append(len(produced))
        all_candidates.extend(produced)
        if len(all_candidates) >= max_raw:
            break
    report.raw_candidates = len(all_candidates)

    if not all_candidates:
        if verbose:
            for line in report.lines():
                print(line)
        return [], report

    # --- SELECTION: só agora filtramos ---
    analyze_all(
        all_candidates, analyzer,
        weights=(config.get("editorial", {}) or {}) or None,
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
    report.after_score_floor = len(viable)

    unique = deduplicate_candidates(
        viable,
        text_threshold=float(dedup_cfg.get("semantic_similarity_threshold", 0.75)),
    )
    report.after_dedup = len(unique)

    if selection_cfg.get("diversity_enabled", True):
        final = select_with_diversity(
            unique,
            max_clips=int(selection_cfg.get("max_final_clips", 10)),
            category_weight=float(selection_cfg.get("category_diversity_weight", 0.35)),
            temporal_weight=float(selection_cfg.get("temporal_diversity_weight", 0.2)),
        )
    else:
        final = sorted(
            unique, key=lambda c: c.heuristic_scores.get("overall", 0), reverse=True
        )[: int(selection_cfg.get("max_final_clips", 10))]
        for c in final:
            c.selected = True
    report.final = len(final)

    if verbose:
        for line in report.lines():
            print(line)

    return final, report
