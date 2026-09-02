"""
Transforma sinais brutos (cortes de cena + picos de áudio) em "momentos candidatos"
com início/fim, e calcula o Content Score de cada um.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import uuid

from core.detection import RawSignal
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

    def weighted_total(self, weights: dict) -> float:
        total_weight = sum(weights.values()) or 1.0
        score = sum(getattr(self, key) * weight for key, weight in weights.items())
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


HYPE_KEYWORDS = [
    "no way", "let's go", "insane", "unbelievable", "oh my god", "what the",
    "holy", "clutch", "ez", "gg", "wow", "yo", "bro",
    "não acredito", "eu não acredito", "que isso", "vai vai", "isso aí",
    "meu deus", "caraca", "mano", "cara", "insano", "absurdo",
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


def _score_cluster(cluster: list[RawSignal], transcript_excerpt: str) -> ContentScoreBreakdown:
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

    return ContentScoreBreakdown(
        gameplay_intensity=round(gameplay_intensity, 1),
        emotional_reaction=emotional_reaction,
        narrative_context=round(narrative_context, 1),
        retention_potential=retention_potential,
        originality=originality,
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


def build_candidate_moments(
    signals: list[RawSignal],
    transcript: list[TranscriptSegment],
    config: dict,
) -> list[CandidateMoment]:
    cand_cfg = config["candidate_moments"]
    weights = config["content_score_weights"]

    clusters = _cluster_signals(
        signals,
        cluster_gap_seconds=cand_cfg.get("cluster_gap_seconds", 5.0),
    )

    moments = []
    for cluster in clusters:
        raw_start = cluster[0].timestamp_seconds
        raw_end = cluster[-1].timestamp_seconds + cand_cfg["min_duration_seconds"] / 2
        if raw_end - raw_start < cand_cfg["min_duration_seconds"]:
            raw_end = raw_start + cand_cfg["min_duration_seconds"]
        raw_end = min(raw_end, raw_start + cand_cfg["max_duration_seconds"])

        context_start = _apply_context_builder(raw_start, transcript, cand_cfg["context_padding_seconds"])
        excerpt = text_around(transcript, raw_start, window_seconds=cand_cfg["context_padding_seconds"])
        segments = _segments_in_range(transcript, context_start, raw_end)
        words = _words_in_range(transcript, context_start, raw_end)

        breakdown = _score_cluster(cluster, excerpt)
        total_score = breakdown.weighted_total(weights)

        moments.append(CandidateMoment(
            clip_id=f"CLIP-{uuid.uuid4().hex[:8].upper()}",
            start_seconds=raw_start,
            end_seconds=raw_end,
            context_start_seconds=context_start,
            transcript_excerpt=excerpt,
            breakdown=breakdown,
            score=total_score,
            signal_sources=list({s.source for s in cluster}),
            transcript_segments=segments,
            transcript_words=words,
        ))

    moments.sort(key=lambda m: m.score, reverse=True)
    moments = _suppress_overlapping(
        moments,
        min_gap_seconds=cand_cfg.get("min_gap_between_clips_seconds", 15.0),
    )
    return moments