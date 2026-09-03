"""
Agrupamento em HISTÓRIAS — Rebuild do motor de clipping.

O PROBLEMA: proximidade temporal não significa mesmo conteúdo. O sistema
antigo juntava tudo que estivesse perto, e separava tudo que estivesse a
mais de 15s — os dois critérios errados pelo mesmo motivo: olhavam o
relógio, não o conteúdo.

O QUE ESTE MÓDULO DECIDE: dados dois eventos próximos, eles são
    setup → payoff → reação   (uma história, um clipe)
ou
    dois acontecimentos independentes   (dois clipes)

CRITÉRIOS PARA JUNTAR (precisa de mais de um):
  1. Continuidade de fala — a pessoa não parou de falar entre os dois.
  2. Escalada — a intensidade cresce do primeiro pro segundo (setup→payoff).
  3. Complementaridade — categorias que formam narrativa juntas
     (ex: action seguido de reaction = jogada + reação a ela).

CRITÉRIOS PARA SEPARAR:
  - Silêncio longo entre eles (a história acabou).
  - Duas categorias fortes e iguais (dois clutches são dois clipes).
  - A junção passaria do limite de duração de short-form.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.events import (
    ACTION, CLUTCH, DEFEAT, HYPE, LAUGHTER, QUOTE, REACTION, STORY, UNKNOWN,
    VICTORY, Event,
)
from core.transcription import TranscriptSegment

# Pares que formam narrativa: (antes, depois).
COMPLEMENTARY = {
    (ACTION, REACTION), (ACTION, LAUGHTER), (ACTION, HYPE),
    (CLUTCH, REACTION), (CLUTCH, LAUGHTER), (CLUTCH, HYPE),
    (VICTORY, REACTION), (VICTORY, LAUGHTER), (DEFEAT, REACTION),
    (HYPE, ACTION), (HYPE, CLUTCH), (HYPE, VICTORY),
    (QUOTE, REACTION), (QUOTE, LAUGHTER), (STORY, REACTION), (STORY, LAUGHTER),
    (UNKNOWN, REACTION), (UNKNOWN, LAUGHTER),
}

# Categorias que, repetidas, quase sempre são acontecimentos distintos.
STANDALONE = {CLUTCH, VICTORY, DEFEAT}


@dataclass
class Story:
    """Um ou mais eventos que formam um clipe potencial."""
    events: list[Event]
    reason: str = ""          # por que foram juntados (útil pra debug e UI)

    @property
    def start_seconds(self) -> float:
        return min(e.start_seconds for e in self.events)

    @property
    def end_seconds(self) -> float:
        return max(e.end_seconds for e in self.events)

    @property
    def intensity(self) -> float:
        return max(e.intensity for e in self.events)

    @property
    def categories(self) -> list[str]:
        return [e.category for e in self.events]

    @property
    def main_category(self) -> str:
        """A categoria do evento mais forte — é o que define o clipe."""
        strongest = max(
            self.events,
            key=lambda e: (e.confidence * 0.6 + e.intensity * 0.4),
        )
        return strongest.category

    @property
    def has_payoff_and_reaction(self) -> bool:
        """História completa: acontece algo E há reação a isso."""
        cats = self.categories
        acted = any(c in (ACTION, CLUTCH, VICTORY, DEFEAT) for c in cats)
        reacted = any(c in (REACTION, LAUGHTER) for c in cats)
        return acted and reacted


def _speech_gap(
    transcript: list[TranscriptSegment], start: float, end: float
) -> float:
    """
    Maior silêncio entre dois pontos. Silêncio longo = a história acabou.

    Sem transcrição, devolve 0.0 — na dúvida, não separa por este critério
    (outros critérios ainda decidem).
    """
    if end <= start or not transcript:
        return 0.0
    inside = sorted(
        (s for s in transcript if s.end_seconds > start and s.start_seconds < end),
        key=lambda s: s.start_seconds,
    )
    if not inside:
        return end - start  # silêncio total no intervalo

    biggest = max(inside[0].start_seconds - start, 0.0)
    for a, b in zip(inside, inside[1:]):
        biggest = max(biggest, b.start_seconds - a.end_seconds)
    biggest = max(biggest, end - inside[-1].end_seconds)
    return biggest


def _should_join(
    current: Story,
    nxt: Event,
    transcript: list[TranscriptSegment],
    max_silence: float,
    max_story_seconds: float,
) -> tuple[bool, str]:
    last = current.events[-1]
    gap = nxt.start_seconds - last.end_seconds

    if nxt.end_seconds - current.start_seconds > max_story_seconds:
        return False, "passaria do limite de duração"

    silence = _speech_gap(transcript, last.end_seconds, nxt.start_seconds)
    if silence >= max_silence:
        return False, "silêncio longo entre os dois"

    # Sem transcrição não há como medir silêncio, então o intervalo bruto é
    # a única evidência disponível. Um vão grande separa: é mais seguro
    # produzir dois clipes independentes do que um clipe com um buraco no meio.
    if not transcript and gap >= max_silence:
        return False, "intervalo grande e sem fala pra ligar os dois"

    # Dois acontecimentos fortes do mesmo tipo = dois clipes.
    if last.category in STANDALONE and nxt.category == last.category:
        return False, "dois acontecimentos independentes do mesmo tipo"

    reasons = []
    if silence < max_silence * 0.5 and gap <= max_silence:
        reasons.append("fala contínua")
    if nxt.intensity > last.intensity * 1.15:
        reasons.append("escalada de intensidade")
    if (last.category, nxt.category) in COMPLEMENTARY:
        reasons.append("categorias complementares")

    # Exige DOIS motivos. Um só é fraco demais e volta a ser
    # "juntou porque estava perto".
    if len(reasons) >= 2:
        return True, " + ".join(reasons)
    return False, "sem ligação suficiente"


def build_stories(
    events: list[Event],
    transcript: list[TranscriptSegment],
    max_silence_seconds: float = 4.0,
    max_story_seconds: float = 75.0,
) -> list[Story]:
    """
    Agrupa eventos em histórias.

    Eventos que não se ligam a nada viram histórias de um evento só — e isso
    é correto: um clutch isolado é um clipe legítimo.
    """
    if not events:
        return []

    ordered = sorted(events, key=lambda e: e.start_seconds)
    stories = [Story(events=[ordered[0]])]

    for event in ordered[1:]:
        join, reason = _should_join(
            stories[-1], event, transcript, max_silence_seconds, max_story_seconds
        )
        if join:
            stories[-1].events.append(event)
            stories[-1].reason = reason
        else:
            stories.append(Story(events=[event], reason=reason))

    return stories
