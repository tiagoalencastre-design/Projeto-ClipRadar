"""
Ponte entre o modelo V2 e o formato que o resto do app já consome.

POR QUE ESTE ARQUIVO EXISTE:

    O modelo principal da V2 é ClipCandidate (core/candidates.py). Mas o
    analysis.json, o montage.py e o front-end foram escritos contra o
    formato antigo (CandidateMoment). Trocar tudo de uma vez quebraria a
    interface do usuário.

    Este adaptador converte ClipCandidate -> dicionário com AS CHAVES
    ANTIGAS preenchidas, e os dados novos da V2 ao lado.

    Assim:
      - o front-end continua funcionando sem nenhuma alteração;
      - quem quiser os dados da V2 lê as chaves novas;
      - existe UM só modelo tomando decisões (ClipCandidate).

IMPORTANTE: este arquivo NÃO toma decisão editorial nenhuma. Ele só
traduz. Toda escolha de clipe acontece em core/discovery.py.
"""
from __future__ import annotations

from core.candidates import ClipCandidate
from core.transcription import TranscriptSegment


def _segments_in_range(
    transcript: list[TranscriptSegment], start: float, end: float
) -> list[dict]:
    return [
        {"start_seconds": s.start_seconds, "end_seconds": s.end_seconds, "text": s.text}
        for s in transcript
        if s.end_seconds > start and s.start_seconds < end
    ]


def _words_in_range(
    transcript: list[TranscriptSegment], start: float, end: float
) -> list[dict]:
    words = []
    for segment in transcript:
        for word in getattr(segment, "words", None) or []:
            w_start = word.get("start", word.get("start_seconds"))
            w_end = word.get("end", word.get("end_seconds"))
            if w_start is None or w_end is None:
                continue
            if w_end > start and w_start < end:
                words.append({
                    "word": word.get("word", word.get("text", "")),
                    "start_seconds": w_start,
                    "end_seconds": w_end,
                })
    return words


def _breakdown_from_scores(scores: dict) -> dict:
    """
    Preenche as chaves de breakdown que o front-end já espera, usando as
    notas editoriais da V2. As chaves novas vão junto, sem substituir.
    """
    return {
        # chaves antigas — o front-end lê estas
        "gameplay_intensity": scores.get("emotion", 0.0),
        "emotional_reaction": scores.get("emotion", 0.0),
        "narrative_context": scores.get("context", 0.0),
        "retention_potential": scores.get("standalone", 0.0),
        "originality": scores.get("originality", 0.0),
        "chat_reaction": 0.0,
        "comment_potential": 0.0,
        "hook": scores.get("hook", 0.0),
        "surprise": 0.0,
        "visual_clarity": 0.0,
        "ending_quality": scores.get("ending", 0.0),
        "story_completeness": scores.get("narrative_completeness", 0.0),
        "share_potential": 0.0,
        "vertical_suitability": 0.0,
        "viral_potential": 0.0,
        # chaves novas da V2
        "standalone": scores.get("standalone", 0.0),
        "context": scores.get("context", 0.0),
        "payoff": scores.get("payoff", 0.0),
    }


def candidate_to_moment(
    candidate: ClipCandidate, transcript: list[TranscriptSegment]
) -> dict:
    """
    ClipCandidate -> dicionário no formato do analysis.json.

    As chaves antigas (clip_id, score, start_seconds, end_seconds,
    context_start_seconds, transcript_excerpt, breakdown, transcript_words,
    transcript_segments) são preenchidas para compatibilidade.
    """
    scores = candidate.heuristic_scores or {}
    return {
        # --- formato antigo, consumido por montage.py e pelo front-end ---
        "clip_id": candidate.candidate_id.replace("cand_", "CLIP-").upper(),
        "score": scores.get("overall", 0.0),
        "start_seconds": candidate.start_seconds,
        "end_seconds": candidate.end_seconds,
        "context_start_seconds": candidate.start_seconds,
        "transcript_excerpt": candidate.transcript,
        "breakdown": _breakdown_from_scores(scores),
        "transcript_segments": _segments_in_range(
            transcript, candidate.start_seconds, candidate.end_seconds),
        "transcript_words": _words_in_range(
            transcript, candidate.start_seconds, candidate.end_seconds),
        "signal_sources": sorted({
            s.source for e in candidate.events for s in e.signals
        }),
        "category": candidate.category,
        "edit_plan": None,   # preenchido depois, pelo montage
        # --- dados novos da V2 ---
        "candidate_id": candidate.candidate_id,
        "story_id": candidate.story_id,
        "candidate_type": candidate.candidate_type,
        "duration_seconds": round(candidate.duration_seconds, 2),
        "payoff_seconds": candidate.payoff_seconds,
        "before_context": candidate.before_context,
        "after_context": candidate.after_context,
        "boundary_reason": candidate.boundary_reason,
        "scores": scores,
        "selected": candidate.selected,
        "selection_reason": candidate.selection_reason,
        "signals": candidate.signals,
    }


def candidates_to_moments(
    candidates: list[ClipCandidate], transcript: list[TranscriptSegment]
) -> list[dict]:
    return [candidate_to_moment(c, transcript) for c in candidates]
