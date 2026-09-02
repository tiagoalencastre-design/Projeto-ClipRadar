"""
Sinais do Content Score, um a um — Fase 5.

O QUE MUDOU: antes, todos os sinais eram calculados dentro de uma função
só (_score_cluster no scoring.py). Agora cada sinal é uma função isolada,
registrada aqui, que pode ser testada e ajustada sozinha.

REGRA QUE ORIENTOU ESTA FASE — "não inventar score sem dado":
    Só implementei os sinais que dá pra calcular com o que o pipeline
    realmente extrai hoje (picos de áudio, cortes de cena, transcrição).
    Os outros ficam DECLARADOS, com peso 0 e implementação ausente, até
    existir dado de verdade pra eles.

    Um número inventado é pior que nenhum número: ele parece informação,
    entra na média, e desloca a escolha dos melhores momentos sem que
    ninguém perceba.

ESTADO DOS 13 SINAIS:

    Implementados com dado real (9):
        1. gameplay_intensity   — energia dos picos de áudio
        2. emotional_reaction   — pico máximo + hype na fala
        3. narrative_context    — densidade de fala em volta
        4. retention_potential  — variedade de sinais no trecho
        5. originality          — valor fixo (herdado; ver nota abaixo)
        6. hook                 — força do sinal nos primeiros segundos
        7. surprise             — maior salto brusco de intensidade
        8. visual_clarity       — ritmo de cortes (nem parado, nem caótico)
        9. ending_quality       — o trecho termina em alta ou morre?

    Declarados, sem dado ainda (4) — peso 0, valor 0:
       10. comment_potential    — precisa de dado de audiência
       11. share_potential      — precisa de histórico de publicação
       12. vertical_suitability — precisa da análise de enquadramento,
                                  que só roda DEPOIS do scoring
       13. viral_potential      — precisa de resultado real dos vídeos

    Nota sobre originality: já era um valor fixo (60.0) antes desta fase.
    Mantive como estava pra não alterar os scores existentes, mas ele é o
    próximo candidato a virar cálculo de verdade — hoje não mede nada.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # só pro editor — evita puxar PySceneDetect só pra tipar
    from core.detection import RawSignal


@dataclass(frozen=True)
class SignalContext:
    """Tudo que um sinal pode precisar pra se calcular."""
    cluster: list["RawSignal"]
    transcript_excerpt: str
    start_seconds: float
    end_seconds: float

    @property
    def audio_signals(self) -> list["RawSignal"]:
        return [s for s in self.cluster if s.source == "audio_peak"]

    @property
    def scene_signals(self) -> list["RawSignal"]:
        return [s for s in self.cluster if s.source == "scene_cut"]

    @property
    def duration(self) -> float:
        return max(self.end_seconds - self.start_seconds, 0.1)


@dataclass(frozen=True)
class Signal:
    """Um sinal do Content Score."""
    name: str
    description: str
    compute: Callable[[SignalContext], float] | None  # None = sem dado ainda

    @property
    def is_implemented(self) -> bool:
        return self.compute is not None


def _clamp(value: float) -> float:
    """Todo sinal vive entre 0 e 100 — mantém a soma ponderada comparável."""
    return round(max(0.0, min(float(value), 100.0)), 1)


# ============================================================
# Sinais novos da Fase 5
# ============================================================

def _hook(ctx: SignalContext) -> float:
    """
    Quão forte é o começo do trecho.

    Clipe curto perde o espectador nos 3 primeiros segundos. Se o sinal
    mais forte está lá no início, o clipe "agarra"; se só acontece no
    final, o começo é morno.
    """
    if not ctx.cluster:
        return 0.0

    window = min(3.0, ctx.duration)
    early = [
        s for s in ctx.cluster
        if s.timestamp_seconds - ctx.start_seconds <= window
    ]
    if not early:
        return 25.0  # tem conteúdo, mas nada acontece no começo

    strongest_early = max(s.strength for s in early)
    strongest_overall = max(s.strength for s in ctx.cluster) or 1.0
    ratio = strongest_early / strongest_overall
    return _clamp(strongest_early * 60 + ratio * 40)


def _surprise(ctx: SignalContext) -> float:
    """
    O maior salto brusco de intensidade dentro do trecho.

    Surpresa é mudança, não volume: um trecho que fica alto o tempo todo
    não surpreende. O que surpreende é o silêncio que vira grito.
    """
    if len(ctx.cluster) < 2:
        return 0.0

    ordered = sorted(ctx.cluster, key=lambda s: s.timestamp_seconds)
    jumps = [
        ordered[i + 1].strength - ordered[i].strength
        for i in range(len(ordered) - 1)
    ]
    biggest_jump = max(jumps) if jumps else 0.0
    if biggest_jump <= 0:
        return 10.0  # só decaimento — nada de surpreendente
    return _clamp(biggest_jump * 130)


def _visual_clarity(ctx: SignalContext) -> float:
    """
    O ritmo de cortes de cena está legível?

    Nenhum corte = imagem parada, entediante. Corte demais = confuso,
    ilegível no celular. O meio-termo pontua melhor.
    """
    cuts = len(ctx.scene_signals)
    cuts_per_10s = (cuts / ctx.duration) * 10

    if cuts_per_10s <= 0.2:
        return 45.0                       # praticamente estático
    if cuts_per_10s <= 3.0:
        return _clamp(70 + cuts_per_10s * 10)   # faixa boa
    return _clamp(max(90 - (cuts_per_10s - 3.0) * 18, 20))  # caótico


def _ending_quality(ctx: SignalContext) -> float:
    """
    O trecho termina em alta ou apaga no fim?

    Final morno é o que faz o espectador sair antes de acabar — e clipe
    não terminado prejudica retenção nas plataformas.
    """
    if not ctx.cluster:
        return 0.0

    window = min(4.0, ctx.duration)
    late = [
        s for s in ctx.cluster
        if ctx.end_seconds - s.timestamp_seconds <= window
    ]
    if not late:
        return 30.0  # nada acontece perto do fim

    strongest_late = max(s.strength for s in late)
    average = sum(s.strength for s in ctx.cluster) / len(ctx.cluster) or 0.01
    return _clamp(strongest_late * 70 + min(strongest_late / average, 2.0) * 15)


# ============================================================
# Registro dos 13 sinais
# ============================================================

SIGNALS: tuple[Signal, ...] = (
    # --- os 7 originais continuam calculados no scoring.py (intocados) ---
    Signal("gameplay_intensity", "Energia média dos picos de áudio", None),
    Signal("emotional_reaction", "Pico máximo somado ao hype da fala", None),
    Signal("narrative_context", "Densidade de fala em volta do momento", None),
    Signal("retention_potential", "Variedade de sinais no trecho", None),
    Signal("originality", "Valor fixo herdado — ainda não mede nada", None),
    Signal("chat_reaction", "Reação do chat — precisa de dado de chat", None),
    Signal("comment_potential", "Potencial de comentário — precisa de audiência", None),

    # --- novos, implementados com dado real ---
    Signal("hook", "Força do sinal nos primeiros segundos", _hook),
    Signal("surprise", "Maior salto brusco de intensidade", _surprise),
    Signal("visual_clarity", "Ritmo de cortes: nem parado, nem caótico", _visual_clarity),
    Signal("ending_quality", "O trecho termina em alta ou apaga", _ending_quality),

    # --- declarados, sem dado ainda ---
    Signal("share_potential", "Precisa de histórico de publicação", None),
    Signal("vertical_suitability", "Precisa da análise de enquadramento", None),
    Signal("viral_potential", "Precisa de resultado real dos vídeos", None),
)

NEW_SIGNAL_NAMES = tuple(
    s.name for s in SIGNALS
    if s.is_implemented or s.name in ("share_potential", "vertical_suitability", "viral_potential")
)


def compute_new_signals(ctx: SignalContext) -> dict[str, float]:
    """
    Calcula todos os sinais implementados nesta fase.

    Sinais sem implementação devolvem 0.0 — e, com peso 0 no settings.yaml,
    não afetam o score final de ninguém.
    """
    result: dict[str, float] = {}
    for signal in SIGNALS:
        if signal.name in ("gameplay_intensity", "emotional_reaction",
                           "narrative_context", "retention_potential",
                           "originality", "chat_reaction", "comment_potential"):
            continue  # calculados no scoring.py, não duplicar
        result[signal.name] = signal.compute(ctx) if signal.is_implemented else 0.0
    return result


def explain_signals() -> list[dict]:
    """
    Content Score transparente e explicável — devolve a lista de sinais com
    o estado de cada um. Serve pra interface mostrar ao usuário o que
    realmente pesou na escolha.
    """
    return [
        {"name": s.name, "description": s.description, "implemented": s.is_implemented}
        for s in SIGNALS
    ]
