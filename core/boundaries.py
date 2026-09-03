"""
Onde o clipe começa e termina — Rebuild do motor de clipping.

O PROBLEMA ANTIGO: o fim era aritmética.

    raw_end = último_sinal + min_duration/2
    if muito curto: raw_end = início + min_duration
    raw_end = min(raw_end, início + max_duration)

Nunca olhava a transcrição. Daí o "final artificial" e o corte no meio da
frase. E a duração era REGRA, não consequência do conteúdo.

O QUE MUDA: as bordas são escolhidas pela FALA. A duração é o resultado,
não a meta. Um clipe pode ter 7 segundos ou 40 — o que manda é onde a frase
começa e onde ela termina.

    HOOK    — onde o espectador entra. Início de frase, não meio.
    CONTEXT — o quanto precisa voltar pra frase fazer sentido.
    PAYOFF  — o pico do acontecimento.
    EXIT    — fim de frase depois do payoff (e da reação, se houver).

LIMITES ainda existem, mas como proteção contra caso degenerado — não como
alvo. Um clipe de 3 segundos não funciona em lugar nenhum; um de 3 minutos
não é short-form.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.transcription import TranscriptSegment

# Proteções, não metas.
HARD_MIN_SECONDS = 5.0
HARD_MAX_SECONDS = 90.0


@dataclass(frozen=True)
class ClipBoundaries:
    hook_seconds: float       # onde o clipe começa
    payoff_seconds: float     # o acontecimento principal
    exit_seconds: float       # onde termina
    context_seconds: float    # quanto de contexto foi incluído antes do payoff
    reason: str = ""

    @property
    def duration(self) -> float:
        return max(self.exit_seconds - self.hook_seconds, 0.0)


def _sentence_start_before(
    transcript: list[TranscriptSegment], target: float, max_lookback: float
) -> float | None:
    """
    Início de fala mais antigo dentro da janela de contexto.

    Preferimos voltar até o COMEÇO de uma frase: entrar no meio de uma frase
    é o que faz o espectador não entender o que está acontecendo.
    """
    earliest = target - max_lookback
    starts = [
        seg.start_seconds for seg in transcript
        if earliest <= seg.start_seconds <= target
    ]
    return min(starts) if starts else None


def _sentence_end_after(
    transcript: list[TranscriptSegment], target: float, max_lookahead: float
) -> float | None:
    """
    Fim de fala logo depois do alvo — pra não cortar a pessoa falando.

    Pega o PRIMEIRO fim de frase depois do payoff. Ir além disso começa a
    incluir assunto novo, que é o que deixa o clipe arrastado.
    """
    latest = target + max_lookahead
    ends = [
        seg.end_seconds for seg in transcript
        if target <= seg.end_seconds <= latest
    ]
    return min(ends) if ends else None


def detect_boundaries(
    story,
    transcript: list[TranscriptSegment],
    max_context_seconds: float = 10.0,
    max_tail_seconds: float = 8.0,
    min_seconds: float = HARD_MIN_SECONDS,
    max_seconds: float = HARD_MAX_SECONDS,
) -> ClipBoundaries:
    """
    Decide as bordas de uma história (objeto core.story.Story).

    Sem transcrição, cai num modo simples baseado no próprio evento — o
    pipeline continua funcionando, só com bordas menos precisas.
    """
    payoff = _find_payoff(story)
    reasons = []

    # --- HOOK ---
    hook = _sentence_start_before(transcript, story.start_seconds, max_context_seconds)
    if hook is not None:
        reasons.append("começa no início da fala")
    else:
        hook = max(story.start_seconds - max_context_seconds / 2, 0.0)
        reasons.append("sem fala antes — contexto por tempo")

    # --- EXIT ---
    tail_from = max(payoff, story.end_seconds)
    exit_at = _sentence_end_after(transcript, tail_from, max_tail_seconds)
    if exit_at is not None:
        reasons.append("termina no fim da frase")
    else:
        exit_at = tail_from + 1.5
        reasons.append("sem fala depois — corte curto após o payoff")

    # --- Proteções (não são metas) ---
    if exit_at - hook < min_seconds:
        exit_at = hook + min_seconds
        reasons.append("estendido ao mínimo utilizável")
    if exit_at - hook > max_seconds:
        # Corta pela frente: preservar o payoff importa mais que o contexto.
        hook = max(exit_at - max_seconds, 0.0)
        reasons.append("cortado ao máximo de short-form")

    return ClipBoundaries(
        hook_seconds=round(hook, 2),
        payoff_seconds=round(payoff, 2),
        exit_seconds=round(exit_at, 2),
        context_seconds=round(max(payoff - hook, 0.0), 2),
        reason=" · ".join(reasons),
    )


def _find_payoff(story) -> float:
    """
    O payoff é o instante do evento mais forte da história.

    Usa intensidade, não posição: numa história setup→clutch→reação, o
    clutch é o payoff, mesmo estando no meio.
    """
    strongest = max(story.events, key=lambda e: e.intensity)
    return (strongest.start_seconds + strongest.end_seconds) / 2
