"""
Geração de CANDIDATOS — ClipRadar V2.

A MUDANÇA CENTRAL DESTA VERSÃO:

    ANTES:  Story  ->  1 clipe
    AGORA:  Story  ->  vários candidatos, e a seleção decide depois

Uma mesma história pode virar clipes editorialmente diferentes. O mesmo
clutch pode ser:

    - a história completa (setup longo, payoff, reação)   -> 34s
    - só o payoff e a reação                              -> 12s
    - a frase forte antes + o acontecimento               -> 18s

Nenhuma dessas leituras é "a certa". São propostas diferentes, e o ranking
editorial escolhe. Descobrir muito e filtrar depois é o oposto do sistema
antigo, que filtrava enquanto descobria e por isso perdia oportunidades.

TIPOS DE CANDIDATO (§6 da spec):
    FULL_STORY       história inteira: início natural, setup, payoff, reação
    PAYOFF_REACTION  contexto mínimo, o acontecimento e a reação
    HOOK_PAYOFF      frase forte antes + o acontecimento
    REACTION         só a reação, quando ela se sustenta sozinha
    MOMENT           acontecimento pontual (clutch, fail, vitória)
    CONTEXTUAL       versão com mais contexto, pra história que precisa

Nem todo tipo faz sentido pra toda história. O gerador só cria o que a
história comporta — inventar candidatos vazios só polui o ranking.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from core.boundaries import ClipBoundaries, detect_boundaries
from core.events import LAUGHTER, REACTION, Event
from core.transcription import TranscriptSegment, text_around

FULL_STORY = "FULL_STORY"
PAYOFF_REACTION = "PAYOFF_REACTION"
HOOK_PAYOFF = "HOOK_PAYOFF"
REACTION_ONLY = "REACTION"
MOMENT = "MOMENT"
CONTEXTUAL = "CONTEXTUAL"


@dataclass
class ClipCandidate:
    """
    Uma proposta editorial de clipe.

    A estrutura segue o §23 da spec: tem tudo que uma IA futura precisaria
    receber, sem que nenhuma IA seja chamada agora.
    """
    candidate_id: str
    story_id: str
    candidate_type: str
    start_seconds: float
    end_seconds: float
    transcript: str = ""
    before_context: str = ""
    after_context: str = ""
    events: list[Event] = field(default_factory=list)
    category: str = "unknown"
    hook_seconds: float = 0.0
    payoff_seconds: float = 0.0
    boundary_reason: str = ""
    signals: dict = field(default_factory=dict)
    heuristic_scores: dict = field(default_factory=dict)
    selected: bool = False
    selection_reason: str = ""

    @property
    def duration_seconds(self) -> float:
        return max(self.end_seconds - self.start_seconds, 0.0)

    def as_dict(self) -> dict:
        """Relatório por candidato (§32) — serve pra debug e pra futura IA."""
        return {
            "candidate_id": self.candidate_id,
            "story_id": self.story_id,
            "candidate_type": self.candidate_type,
            "start": round(self.start_seconds, 2),
            "end": round(self.end_seconds, 2),
            "duration": round(self.duration_seconds, 2),
            "category": self.category,
            "scores": self.heuristic_scores,
            "signals": self.signals,
            "boundary_reason": self.boundary_reason,
            "selection": {
                "selected": self.selected,
                "reason": self.selection_reason,
            },
        }


def _make(
    story_id: str, kind: str, story, boundaries: ClipBoundaries,
    transcript: list[TranscriptSegment], start: float, end: float,
) -> ClipCandidate | None:
    """Monta um candidato, ou None se o recorte não sobrou nada utilizável."""
    if end - start < 3.0:
        return None
    return ClipCandidate(
        candidate_id=f"cand_{uuid.uuid4().hex[:8]}",
        story_id=story_id,
        candidate_type=kind,
        start_seconds=round(start, 2),
        end_seconds=round(end, 2),
        transcript=_speech_between(transcript, start, end),
        before_context=text_around(transcript, start, window_seconds=12.0),
        after_context=text_around(transcript, end, window_seconds=8.0),
        events=list(story.events),
        category=story.main_category,
        hook_seconds=round(start, 2),
        payoff_seconds=boundaries.payoff_seconds,
        boundary_reason=boundaries.reason,
        signals={
            "intensity": round(story.intensity, 3),
            "event_count": len(story.events),
            "categories": story.categories,
        },
    )


def _speech_between(transcript: list[TranscriptSegment], start: float, end: float) -> str:
    return " ".join(
        seg.text for seg in transcript
        if seg.end_seconds > start and seg.start_seconds < end
    ).strip()


def _sentence_start_nearest(
    transcript: list[TranscriptSegment], target: float, window: float
) -> float:
    """Início de frase mais próximo do alvo, pra não cortar no meio."""
    starts = [
        s.start_seconds for s in transcript
        if abs(s.start_seconds - target) <= window
    ]
    return min(starts, key=lambda s: abs(s - target)) if starts else target


def generate_candidates(
    story,
    transcript: list[TranscriptSegment],
    config: dict | None = None,
) -> list[ClipCandidate]:
    """
    Gera as leituras editoriais possíveis de uma história.

    Sempre devolve pelo menos um candidato quando a história é utilizável —
    perder uma história inteira por não conseguir recortá-la seria pior que
    ter um candidato mediano no ranking.
    """
    cfg = config or {}
    story_id = f"story_{uuid.uuid4().hex[:6]}"
    boundaries = detect_boundaries(
        story, transcript,
        max_context_seconds=cfg.get("max_context_seconds", 45.0),
        max_tail_seconds=cfg.get("tail_padding_seconds", 8.0),
        min_seconds=cfg.get("absolute_min_seconds", 8.0),
        max_seconds=cfg.get("absolute_max_seconds", 75.0),
    )

    candidates: list[ClipCandidate] = []

    def add(kind: str, start: float, end: float) -> None:
        c = _make(story_id, kind, story, boundaries, transcript, start, end)
        if c:
            candidates.append(c)

    hook, payoff, exit_at = (
        boundaries.hook_seconds, boundaries.payoff_seconds, boundaries.exit_seconds
    )

    # 1) A história como as bordas indicam.
    add(FULL_STORY if len(story.events) > 1 else MOMENT, hook, exit_at)

    # 2) Versão curta: entra pouco antes do payoff, mantém a reação.
    #    Muitos acontecimentos funcionam melhor sem preâmbulo.
    if payoff - hook > 6.0:
        short_start = _sentence_start_nearest(transcript, payoff - 4.0, 4.0)
        add(PAYOFF_REACTION, short_start, exit_at)

    # 3) Hook + payoff, sem a cauda — quando existe fala forte antes.
    if exit_at - payoff > 5.0:
        add(HOOK_PAYOFF, hook, min(payoff + 4.0, exit_at))

    # 4) Só a reação, quando há uma que se sustenta sozinha.
    reactions = [e for e in story.events if e.category in (REACTION, LAUGHTER)]
    if reactions:
        r = max(reactions, key=lambda e: e.intensity)
        r_start = _sentence_start_nearest(transcript, r.start_seconds - 2.0, 4.0)
        add(REACTION_ONLY, r_start, min(r.end_seconds + 4.0, exit_at))

    # 5) Versão com mais contexto, pra história que precisa de explicação.
    if len(story.events) > 1 and hook > 0:
        wider = _sentence_start_nearest(transcript, hook - 10.0, 10.0)
        if wider < hook - 2.0:
            add(CONTEXTUAL, wider, exit_at)

    return _drop_near_identical(candidates)


def _drop_near_identical(candidates: list[ClipCandidate]) -> list[ClipCandidate]:
    """
    Tira candidatos praticamente iguais DENTRO da mesma história.

    Se dois recortes diferem por menos de 2 segundos nas duas pontas, são a
    mesma proposta com nome diferente — mantê-los só inflaria o ranking.
    """
    kept: list[ClipCandidate] = []
    for c in candidates:
        twin = any(
            abs(c.start_seconds - k.start_seconds) < 2.0
            and abs(c.end_seconds - k.end_seconds) < 2.0
            for k in kept
        )
        if not twin:
            kept.append(c)
    return kept
