"""
Transforma sinais brutos (cortes de cena + picos de áudio) em "momentos candidatos"
com início/fim, e calcula o Content Score de cada um.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import uuid

from core.boundaries import detect_boundaries
from core.dedup import deduplicate
from core.detection import RawSignal
from core.events import build_events
from core.scoring_signals import SignalContext, compute_new_signals
from core.story import build_stories
from core.transcription import TranscriptSegment, text_around


@dataclass
class ContentScoreBreakdown:
    gameplay_intensity: float
    emotional_reaction: float
    narrative_context: float
    retention_potential: float
    originality: float
    chat_reaction: float = 0.0
    comment_potential: float = 0.0

    # FASE 5 — sinais novos. Todos entram com peso 0.0 no settings.yaml, ou
    # seja: aparecem no relatório, mas NÃO alteram nenhum score existente
    # até você decidir dar peso a eles.
    hook: float = 0.0
    surprise: float = 0.0
    # REBUILD: peso alto de propósito. Um momento intenso que não se entende
    # sozinho NÃO deve vencer um clipe completo e compreensível.
    story_completeness: float = 0.0
    visual_clarity: float = 0.0
    ending_quality: float = 0.0
    # Declarados, sem dado real ainda — ficam em 0.0 de propósito.
    share_potential: float = 0.0
    vertical_suitability: float = 0.0
    viral_potential: float = 0.0

    def weighted_total(self, weights: dict) -> float:
        """Peso desconhecido é ignorado em vez de quebrar — assim um typo no
        settings.yaml não derruba a análise inteira."""
        known = {k: w for k, w in weights.items() if hasattr(self, k)}
        total_weight = sum(known.values()) or 1.0
        score = sum(getattr(self, key) * weight for key, weight in known.items())
        return round((score / total_weight), 1)


@dataclass
class CandidateMoment:
    clip_id: str
    start_seconds: float
    end_seconds: float
    context_start_seconds: float
    transcript_excerpt: str
    breakdown: ContentScoreBreakdown
    score: float
    signal_sources: list[str] = field(default_factory=list)
    transcript_segments: list[dict] = field(default_factory=list)
    transcript_words: list[dict] = field(default_factory=list)
    # REBUILD — campos novos. Opcionais: quem consumia o formato antigo
    # continua funcionando sem alteração.
    category: str = "unknown"
    confidence: float = 0.0
    payoff_seconds: float = 0.0
    boundary_reason: str = ""
    story_reason: str = ""
    event_count: int = 1


def _cluster_signals(signals: list[RawSignal], cluster_gap_seconds: float) -> list[list[RawSignal]]:
    if not signals:
        return []

    clusters: list[list[RawSignal]] = [[signals[0]]]
    for sig in signals[1:]:
        last_cluster = clusters[-1]
        gap = sig.timestamp_seconds - last_cluster[-1].timestamp_seconds
        if gap <= cluster_gap_seconds:
            last_cluster.append(sig)
        else:
            clusters.append([sig])
    return clusters


def _apply_context_builder(cluster_start: float, transcript: list[TranscriptSegment], padding_seconds: float) -> float:
    earliest_allowed = cluster_start - padding_seconds
    candidates = [
        seg.start_seconds for seg in transcript
        if earliest_allowed <= seg.start_seconds <= cluster_start
    ]
    if candidates:
        return min(candidates)
    return max(cluster_start - padding_seconds / 2, 0)


# REBUILD: "mano", "cara", "bro", "yo" saíram desta lista. Em português
# falado são muletas — aparecem em quase toda frase e geravam falso
# positivo em escala, inflando o score de trechos comuns.
HYPE_KEYWORDS = [
    "no way", "let's go", "insane", "unbelievable", "oh my god", "what the",
    "holy", "clutch", "ez", "gg", "wow",
    "não acredito", "eu não acredito", "que isso", "vai vai", "isso aí",
    "meu deus", "caraca", "caramba", "insano", "absurdo", "surreal",
]


def _hype_boost(transcript_excerpt: str) -> float:
    if not transcript_excerpt:
        return 0.0

    text_lower = transcript_excerpt.lower()
    keyword_hits = sum(1 for kw in HYPE_KEYWORDS if kw in text_lower)

    exclamation_boost = min(transcript_excerpt.count("!") * 3, 12)
    caps_words = [w for w in transcript_excerpt.split() if len(w) >= 3 and w.isupper()]
    caps_boost = min(len(caps_words) * 4, 12)

    keyword_boost = min(keyword_hits * 6, 18)

    return min(keyword_boost + exclamation_boost + caps_boost, 30.0)


def _score_cluster(
    cluster: list[RawSignal],
    transcript_excerpt: str,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
) -> ContentScoreBreakdown:
    audio_signals = [s for s in cluster if s.source == "audio_peak"]
    scene_signals = [s for s in cluster if s.source == "scene_cut"]

    gameplay_intensity = min(
        (sum(s.strength for s in audio_signals) / max(len(audio_signals), 1)) * 100 if audio_signals else 40.0,
        100.0,
    )

    all_strengths = [s.strength for s in cluster]
    base_emotional_reaction = round(max(all_strengths) * 100, 1) if all_strengths else 30.0
    emotional_reaction = min(base_emotional_reaction + _hype_boost(transcript_excerpt), 100.0)

    base_narrative = min(len(transcript_excerpt.split()) * 3, 100.0) if transcript_excerpt else 20.0
    narrative_context = min(base_narrative + _hype_boost(transcript_excerpt) * 0.5, 100.0)

    retention_potential = min(50.0 + (len(scene_signals) * 10) + (len(audio_signals) * 8), 100.0)

    originality = 60.0

    # FASE 5: sinais novos, calculados em core/scoring_signals.py (cada um
    # isolado e testável). Só rodam se soubermos o intervalo do trecho.
    new_signals = {}
    if start_seconds is not None and end_seconds is not None:
        new_signals = compute_new_signals(SignalContext(
            cluster=cluster,
            transcript_excerpt=transcript_excerpt,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
        ))

    return ContentScoreBreakdown(
        gameplay_intensity=round(gameplay_intensity, 1),
        emotional_reaction=emotional_reaction,
        narrative_context=round(narrative_context, 1),
        retention_potential=retention_potential,
        originality=originality,
        **new_signals,
    )


def _suppress_overlapping(moments: list[CandidateMoment], min_gap_seconds: float) -> list[CandidateMoment]:
    accepted: list[CandidateMoment] = []
    for candidate in moments:
        overlaps_or_too_close = any(
            candidate.context_start_seconds < kept.end_seconds + min_gap_seconds
            and kept.context_start_seconds < candidate.end_seconds + min_gap_seconds
            for kept in accepted
        )
        if not overlaps_or_too_close:
            accepted.append(candidate)
    return accepted


def _segments_in_range(transcript: list[TranscriptSegment], start: float, end: float) -> list[dict]:
    return [
        {"start": seg.start_seconds, "end": seg.end_seconds, "text": seg.text}
        for seg in transcript
        if seg.end_seconds > start and seg.start_seconds < end
    ]


def _words_in_range(transcript: list[TranscriptSegment], start: float, end: float) -> list[dict]:
    words = []
    for seg in transcript:
        if seg.end_seconds <= start or seg.start_seconds >= end:
            continue
        for w in seg.words:
            if w["end"] > start and w["start"] < end:
                words.append(w)
    return words


def _story_completeness(story, boundaries) -> float:
    """
    O clipe se entende sozinho?

    Esta é a métrica que o briefing pede com peso significativo — e o motivo
    é editorial: um grito sem contexto tem intensidade alta e valor zero.
    """
    score = 30.0
    if boundaries.context_seconds >= 2.0:
        score += 20.0            # tem preparação antes do payoff
    if story.has_payoff_and_reaction:
        score += 25.0            # acontece algo E há reação
    if len(story.events) > 1:
        score += 10.0            # tem desenvolvimento, não é um pico solto
    if "início da fala" in boundaries.reason:
        score += 10.0            # não começa no meio de uma frase
    if "fim da frase" in boundaries.reason:
        score += 5.0             # não corta a pessoa falando
    return min(score, 100.0)


def build_candidate_moments(
    signals: list[RawSignal],
    transcript: list[TranscriptSegment],
    config: dict,
) -> list[CandidateMoment]:
    """
    ⚠️ LEGADO — NÃO É MAIS USADO PELO PIPELINE DE PRODUÇÃO.

    Desde a integração da V2, quem descobre e seleciona os clipes é
    core/discovery.py -> discover_and_select(). Esta função continua aqui
    apenas porque:

      - gera 1 candidato por história (a limitação que a V2 veio resolver);
      - serve de referência pra comparar resultados antigo x novo;
      - alguma ferramenta externa pode ainda importá-la.

    NÃO ligue isto de volta no pipeline: teria dois sistemas de seleção
    concorrentes, que é exatamente o problema que a V2 eliminou.

    Se for usar, saiba que o modelo principal do projeto hoje é
    ClipCandidate (core/candidates.py), não CandidateMoment.
    """
    cand_cfg = config["candidate_moments"]
    weights = config["content_score_weights"]

    events = build_events(
        signals, transcript,
        window_seconds=cand_cfg.get("event_window_seconds", 6.0),
    )
    stories = build_stories(
        events, transcript,
        max_silence_seconds=cand_cfg.get("story_max_silence_seconds", 4.0),
        max_story_seconds=cand_cfg.get("max_duration_seconds", 75.0),
    )

    moments = []
    for story in stories:
        boundaries = detect_boundaries(
            story, transcript,
            max_context_seconds=cand_cfg.get("context_padding_seconds", 10.0),
            max_tail_seconds=cand_cfg.get("tail_padding_seconds", 8.0),
            min_seconds=cand_cfg.get("min_duration_seconds", 5.0),
            max_seconds=cand_cfg.get("max_duration_seconds", 75.0),
        )

        cluster = [s for e in story.events for s in e.signals]
        excerpt = text_around(
            transcript, boundaries.payoff_seconds,
            window_seconds=max(boundaries.duration / 2, 5.0),
        )
        breakdown = _score_cluster(
            cluster, excerpt, boundaries.hook_seconds, boundaries.exit_seconds
        )
        breakdown.story_completeness = _story_completeness(story, boundaries)
        total_score = breakdown.weighted_total(weights)

        moments.append(CandidateMoment(
            clip_id=f"CLIP-{uuid.uuid4().hex[:8].upper()}",
            start_seconds=boundaries.hook_seconds,
            end_seconds=boundaries.exit_seconds,
            context_start_seconds=boundaries.hook_seconds,
            transcript_excerpt=excerpt,
            breakdown=breakdown,
            score=total_score,
            signal_sources=sorted({s.source for s in cluster}),
            transcript_segments=_segments_in_range(
                transcript, boundaries.hook_seconds, boundaries.exit_seconds),
            transcript_words=_words_in_range(
                transcript, boundaries.hook_seconds, boundaries.exit_seconds),
            category=story.main_category,
            confidence=round(max(e.confidence for e in story.events), 3),
            payoff_seconds=boundaries.payoff_seconds,
            boundary_reason=boundaries.reason,
            story_reason=story.reason,
            event_count=len(story.events),
        ))

    moments.sort(key=lambda m: m.score, reverse=True)

    # REBUILD: dedup por CONTEÚDO, não por distância de relógio. Dois
    # momentos podem ficar próximos e ambos sobreviverem, desde que cubram
    # acontecimentos diferentes.
    as_dicts = [
        {"context_start_seconds": m.context_start_seconds,
         "end_seconds": m.end_seconds,
         "transcript_excerpt": m.transcript_excerpt,
         "score": m.score, "clip_id": m.clip_id}
        for m in moments
    ]
    kept_ids = {d["clip_id"] for d in deduplicate(as_dicts)}
    return [m for m in moments if m.clip_id in kept_ids]
