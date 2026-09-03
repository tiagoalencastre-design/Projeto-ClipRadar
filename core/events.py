"""
Camada de EVENTOS — Rebuild do motor de clipping.

O ERRO CONCEITUAL QUE ISTO CORRIGE: antes, um pico de áudio ERA um momento
candidato. Pico não é acontecimento — é sintoma. Um grito, uma risada e um
tiroteio produzem picos parecidos, mas viram clipes muito diferentes.

Um Evento diz "algo aconteceu aqui, provavelmente deste tipo, com esta
confiança". Ele junta o que veio do áudio, da cena e da fala num objeto só.

DECISÃO IMPORTANTE — por que a classificação é conservadora:
    Categorizar errado é pior que não categorizar. Um evento marcado como
    'clutch' que era só barulho faz o clipe ser editado como clutch (zoom no
    payoff, legenda destacada) e o resultado fica pior do que se fosse
    tratado como genérico. Por isso, sem sinal claro, a categoria fica
    'unknown' e a confiança baixa — e o pipeline segue funcionando.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.detection import RawSignal
from core.transcription import TranscriptSegment

# --- Categorias ---
# Genéricas (funcionam em qualquer conteúdo)
REACTION = "reaction"        # grito, espanto, "não acredito"
LAUGHTER = "laughter"        # risada
HYPE = "hype"                # empolgação sustentada
QUOTE = "quote"              # fala marcante
ACTION = "action"            # intensidade audiovisual sem fala clara
STORY = "story"              # narração/explicação longa
UNKNOWN = "unknown"          # não deu pra dizer — tratado como genérico

# Específicas de gaming (a camada por jogo, no futuro, refina estas)
CLUTCH = "clutch"
VICTORY = "victory"
DEFEAT = "defeat"

# Palavras que indicam reação de verdade. Note o que NÃO está aqui:
# "mano", "cara", "bro" — em português falado são muletas, aparecem em quase
# toda frase, e estavam gerando falso positivo em escala no sistema antigo.
REACTION_WORDS = (
    "não acredito", "nao acredito", "que isso", "meu deus", "caraca", "caramba",
    "pelo amor", "o que foi isso", "que que foi isso", "surreal", "absurdo",
    "insano", "inacreditável", "inacreditavel", "olha isso", "vixe", "eita",
    "no way", "oh my god", "what the", "holy", "unbelievable", "insane",
)
LAUGHTER_WORDS = ("kkkk", "hahaha", "haha", "rsrs", "lol", "morri de rir", "chorando de rir")
HYPE_WORDS = ("vamos", "vai vai", "isso aí", "isso ai", "let's go", "lets go", "boraa", "bora")
VICTORY_WORDS = ("ganhamos", "vencemos", "ganhei", "venci", "gg", "we won", "victory", "eziest")
DEFEAT_WORDS = ("perdemos", "perdi", "tomamos", "acabou", "we lost", "defeat")
CLUTCH_WORDS = ("clutch", "sozinho", "1v3", "1v4", "1v5", "um contra", "peguei todos")


@dataclass
class Event:
    """Algo que aconteceu no vídeo."""
    start_seconds: float
    end_seconds: float
    category: str
    intensity: float          # 0.0–1.0, força do sinal audiovisual
    confidence: float         # 0.0–1.0, quanto confiamos na CATEGORIA
    transcript: str = ""
    sources: list[str] = field(default_factory=list)
    signals: list[RawSignal] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return max(self.end_seconds - self.start_seconds, 0.0)

    @property
    def is_speech_driven(self) -> bool:
        """Se o que define o evento é a fala (importa pro boundary: clipe de
        fala não pode cortar no meio da frase)."""
        return self.category in (REACTION, LAUGHTER, QUOTE, STORY, HYPE)

    def as_dict(self) -> dict:
        return {
            "start": round(self.start_seconds, 2),
            "end": round(self.end_seconds, 2),
            "category": self.category,
            "intensity": round(self.intensity, 3),
            "confidence": round(self.confidence, 3),
            "sources": sorted(self.sources),
        }


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _count_hits(text: str, words: tuple[str, ...]) -> int:
    return sum(1 for w in words if w in text)


def classify(text: str, intensity: float, has_speech: bool) -> tuple[str, float]:
    """
    Decide a categoria e a confiança.

    Devolve (categoria, confiança). Confiança baixa é sinal honesto de "não
    sei" — quem consome deve tratar como genérico, não forçar uma edição
    específica.
    """
    t = _normalize(text)

    if not has_speech or not t:
        # Sem fala: só dá pra dizer que houve atividade audiovisual.
        return (ACTION, 0.45) if intensity >= 0.6 else (UNKNOWN, 0.2)

    scores = {
        LAUGHTER: _count_hits(t, LAUGHTER_WORDS) * 2,
        CLUTCH: _count_hits(t, CLUTCH_WORDS) * 2,
        VICTORY: _count_hits(t, VICTORY_WORDS),
        DEFEAT: _count_hits(t, DEFEAT_WORDS),
        REACTION: _count_hits(t, REACTION_WORDS) * 2 + t.count("!"),
        HYPE: _count_hits(t, HYPE_WORDS),
    }
    best = max(scores, key=lambda k: scores[k])
    best_score = scores[best]

    if best_score == 0:
        # Fala sem marcador: história longa ou fala solta.
        word_count = len(t.split())
        if word_count >= 25:
            return STORY, 0.5
        if word_count >= 8:
            return QUOTE, 0.35
        return UNKNOWN, 0.2

    # Confiança cresce com evidência, mas nunca chega a 1.0: nenhuma
    # heurística de palavra-chave merece certeza total.
    confidence = min(0.35 + best_score * 0.12 + intensity * 0.2, 0.9)
    return best, round(confidence, 3)


def _speech_in(transcript: list[TranscriptSegment], start: float, end: float) -> str:
    return " ".join(
        seg.text for seg in transcript
        if seg.end_seconds > start and seg.start_seconds < end
    ).strip()


def build_events(
    signals: list[RawSignal],
    transcript: list[TranscriptSegment],
    window_seconds: float = 6.0,
) -> list[Event]:
    """
    Agrupa sinais próximos numa janela FIXA e classifica cada grupo.

    A janela é medida a partir do INÍCIO do grupo, não do último sinal —
    esta é a correção do bug de encadeamento: antes, sinais a cada 4s
    encadeavam indefinidamente e 3 minutos viravam um evento só.
    """
    if not signals:
        return []

    ordered = sorted(signals, key=lambda s: s.timestamp_seconds)
    groups: list[list[RawSignal]] = [[ordered[0]]]
    for sig in ordered[1:]:
        group_start = groups[-1][0].timestamp_seconds
        if sig.timestamp_seconds - group_start <= window_seconds:
            groups[-1].append(sig)
        else:
            groups.append([sig])

    events = []
    for group in groups:
        start = group[0].timestamp_seconds
        end = max(group[-1].timestamp_seconds, start + 1.0)
        intensity = max(s.strength for s in group)
        text = _speech_in(transcript, start - 2.0, end + 3.0)
        category, confidence = classify(text, intensity, has_speech=bool(text))
        events.append(Event(
            start_seconds=start, end_seconds=end,
            category=category, intensity=intensity, confidence=confidence,
            transcript=text,
            sources=sorted({s.source for s in group}),
            signals=group,
        ))
    return events
