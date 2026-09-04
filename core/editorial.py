"""
Avaliação editorial dos candidatos — ClipRadar V2.

NENHUMA IA É USADA AQUI. Nenhuma chamada HTTP, nenhuma chave, nenhuma
dependência nova. O que existe é a INTERFACE (§22 da spec) e uma
implementação puramente heurística, local e determinística.

    EditorialAnalyzer            <- contrato
      HeuristicEditorialAnalyzer <- o que roda hoje
      (AIEditorialAnalyzer)      <- futuro, fora desta etapa

O QUE ESTE MÓDULO DECIDE, e por quê:

  standalone_score — "quem assistir só este clipe entende o que aconteceu?"
        É a pergunta que mais separa clipe bom de clipe ruim em short-form,
        e é onde entra a detecção de referência órfã: um clipe que começa
        com "ele fez isso" não se sustenta, por mais intenso que seja.

  context_score — qualidade do contexto, não sua duração. Dez segundos de
        "mano... olha isso... caraca" não explicam nada; quatro segundos de
        "ontem eu tava jogando com meus amigos" explicam.

  hook_score — separado da intensidade de propósito (§9). "Eu quase fui
        banido por causa disso" é um hook excelente em volume normal.

  payoff_score — separado do volume (§11). Punchline e revelação são payoff
        sem pico de áudio.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod

from core.candidates import (
    CONTEXTUAL, FULL_STORY, HOOK_PAYOFF, MOMENT, PAYOFF_REACTION,
    REACTION_ONLY, ClipCandidate,
)
from core.events import CLUTCH, DEFEAT, LAUGHTER, REACTION, VICTORY

# --- Pistas linguísticas (§8, §18) ---

# Conectores que marcam início de pensamento/história. Pistas, não verdade.
NARRATIVE_OPENERS = (
    "então", "entao", "aí", "ai eu", "daí", "dai", "quando", "ontem",
    "eu estava", "eu tava", "tava jogando", "aconteceu", "o problema foi",
    "vocês não sabem", "voces nao sabem", "deixa eu contar", "teve uma vez",
    "outro dia", "olha só", "olha so", "primeiro", "antes de",
)

# Pronomes/dêiticos sem antecedente = clipe que começa no meio da história.
ORPHAN_REFERENCES = (
    "ele", "ela", "eles", "elas", "isso", "isto", "aquilo", "aquele",
    "aquela", "esse", "essa", "lá", "la", "aí", "também", "tambem",
    "de novo", "outra vez", "o cara", "esse cara",
)

# Hook por conteúdo, não por volume.
HOOK_MARKERS = (
    "quase", "nunca", "sempre", "pior", "melhor", "primeira vez",
    "não sabia", "nao sabia", "descobri", "olha o que", "presta atenção",
    "presta atencao", "vocês precisam ver", "voces precisam ver",
    "acredita que", "sabe o que", "adivinha",
)

# Payoff por conteúdo.
PAYOFF_MARKERS = (
    "consegui", "peguei", "ganhei", "perdi", "morri", "aconteceu",
    "no final", "resultado", "e foi assim", "aí que", "ai que",
    "resolvi", "descobri", "virou", "acabou",
)

FILLER_ONLY = {"mano", "cara", "tipo", "assim", "então", "entao", "né", "ne",
               "ah", "eh", "uh", "olha", "isso", "caraca"}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zà-ú0-9']+", (text or "").lower())


def _hits(text: str, markers: tuple[str, ...]) -> int:
    low = (text or "").lower()
    return sum(1 for m in markers if m in low)


def _clamp(v: float) -> float:
    return round(max(0.0, min(v, 100.0)), 1)


def _first_words(text: str, n: int = 8) -> list[str]:
    return _words(text)[:n]


class EditorialAnalyzer(ABC):
    """
    Contrato de avaliação editorial.

    Existe pra que, no futuro, um analisador por IA possa substituir o
    heurístico sem que transcrição, eventos, histórias, geração de
    candidatos, seleção ou renderização mudem uma linha (§33).
    """

    name = "base"

    @abstractmethod
    def analyze_candidate(self, candidate: ClipCandidate, context: dict | None = None) -> dict:
        """Devolve um dicionário de notas 0–100, incluindo 'overall'."""
        raise NotImplementedError


class HeuristicEditorialAnalyzer(EditorialAnalyzer):
    """Avaliação local, determinística, sem custo e sem rede."""

    name = "heuristic"

    # Faixa em que um clipe funciona melhor em short-form. NÃO é uma meta:
    # a duração continua saindo do conteúdo. Isto só reconhece que um clipe
    # de 4s raramente conta uma história e um de 70s raramente segura o
    # espectador até o fim.
    IDEAL_MIN_SECONDS = 15.0
    IDEAL_MAX_SECONDS = 45.0

    DEFAULT_WEIGHTS = {
        "standalone": 1.4,
        "context": 1.1,
        "hook": 1.0,
        "payoff": 1.2,
        "ending": 0.8,
        "emotion": 0.9,
        "narrative_completeness": 1.0,
        # Peso modesto de propósito: a duração continua saindo do conteúdo.
        # Isto só reconhece que 5s raramente conta história e 90s raramente
        # segura o espectador — não força ninguém a ficar na faixa.
        "short_form_fit": 0.6,
        "originality": 0.3,
    }

    def __init__(self, weights: dict | None = None, duration_config: dict | None = None):
        self.weights = {**self.DEFAULT_WEIGHTS, **(weights or {})}
        cfg = duration_config or {}
        self.ideal_min = float(cfg.get("ideal_min_seconds", self.IDEAL_MIN_SECONDS))
        self.ideal_max = float(cfg.get("ideal_max_seconds", self.IDEAL_MAX_SECONDS))

    # ---------- componentes ----------

    def orphan_reference_penalty(self, candidate: ClipCandidate) -> float:
        """
        Quanto o começo do clipe depende de algo que não está nele.

        Só olha as primeiras palavras: "isso" no meio de uma frase já
        explicada é normal; "isso" na primeira palavra é órfão.
        """
        opening = _first_words(candidate.transcript, 8)
        if not opening:
            return 0.0
        orphans = sum(1 for w in opening[:5] if w in ORPHAN_REFERENCES)
        if not orphans:
            return 0.0
        # Um conector narrativo no começo perdoa parcialmente: "aí ele fez
        # isso" ainda é um início de fala, mesmo com pronome.
        if _hits(" ".join(opening), NARRATIVE_OPENERS):
            return min(orphans * 8.0, 20.0)
        return min(orphans * 15.0, 45.0)

    def context_score(self, candidate: ClipCandidate) -> float:
        """
        Qualidade do contexto, não sua duração (§10, §17).
        """
        words = _words(candidate.transcript)
        if not words:
            return 20.0

        meaningful = [w for w in words if w not in FILLER_ONLY and len(w) > 2]
        if not meaningful:
            return 15.0   # só muletas: "mano... olha isso... caraca"

        score = 35.0
        density = len(meaningful) / max(len(words), 1)
        score += density * 25.0                      # fala com substância
        score += min(_hits(candidate.transcript, NARRATIVE_OPENERS) * 10, 20)
        if candidate.payoff_seconds - candidate.start_seconds >= 2.0:
            score += 10.0                            # há preparação
        score -= self.orphan_reference_penalty(candidate) * 0.5
        return _clamp(score)

    def hook_score(self, candidate: ClipCandidate) -> float:
        """Hook por conteúdo E por intensidade — separados de propósito (§9)."""
        opening = " ".join(_first_words(candidate.transcript, 14))
        score = 30.0
        score += min(_hits(opening, HOOK_MARKERS) * 18, 36)
        score += min(_hits(opening, NARRATIVE_OPENERS) * 8, 16)
        if "?" in opening:
            score += 8.0                              # pergunta gera abertura
        score += candidate.signals.get("intensity", 0.0) * 20
        score -= self.orphan_reference_penalty(candidate) * 0.6
        return _clamp(score)

    def payoff_score(self, candidate: ClipCandidate) -> float:
        """Payoff por conteúdo, não só por volume (§11)."""
        score = 35.0
        score += min(_hits(candidate.transcript, PAYOFF_MARKERS) * 12, 30)
        score += candidate.signals.get("intensity", 0.0) * 25
        if candidate.category in (CLUTCH, VICTORY, DEFEAT):
            score += 12.0
        if candidate.category in (REACTION, LAUGHTER):
            score += 6.0
        # O payoff precisa caber no recorte, senão o clipe corta antes dele.
        if not (candidate.start_seconds <= candidate.payoff_seconds <= candidate.end_seconds):
            score -= 30.0
        return _clamp(score)

    def ending_score(self, candidate: ClipCandidate) -> float:
        score = 40.0
        if "fim da frase" in candidate.boundary_reason:
            score += 30.0
        if "corte curto" in candidate.boundary_reason:
            score -= 5.0
        tail = candidate.end_seconds - candidate.payoff_seconds
        if 1.0 <= tail <= 8.0:
            score += 20.0        # respira depois do payoff, sem arrastar
        elif tail > 15.0:
            score -= 15.0        # ficou longo demais depois do acontecimento
        return _clamp(score)

    def standalone_score(self, candidate: ClipCandidate) -> float:
        """
        Assistindo SÓ este clipe, dá pra entender? (§16)
        """
        score = 45.0
        score -= self.orphan_reference_penalty(candidate)
        score += min(len(_words(candidate.transcript)) * 0.6, 25.0)
        if _hits(candidate.transcript, NARRATIVE_OPENERS):
            score += 12.0
        if _hits(candidate.transcript, PAYOFF_MARKERS):
            score += 10.0
        if candidate.candidate_type in (FULL_STORY, CONTEXTUAL):
            score += 8.0
        if candidate.candidate_type == REACTION_ONLY:
            score -= 12.0        # reação solta costuma depender do que veio antes
        return _clamp(score)

    def narrative_completeness(self, candidate: ClipCandidate) -> float:
        cats = [e.category for e in candidate.events]
        score = 30.0
        if len(candidate.events) > 1:
            score += 20.0
        if any(c in (REACTION, LAUGHTER) for c in cats):
            score += 20.0
        if any(c in (CLUTCH, VICTORY, DEFEAT, "action") for c in cats):
            score += 20.0
        if candidate.candidate_type == FULL_STORY:
            score += 10.0
        return _clamp(score)

    def emotion_score(self, candidate: ClipCandidate) -> float:
        score = candidate.signals.get("intensity", 0.0) * 60
        text = candidate.transcript
        score += min(text.count("!") * 4, 16)
        if candidate.category in (REACTION, LAUGHTER):
            score += 20.0
        return _clamp(score + 15.0)

    def short_form_fit(self, candidate: ClipCandidate) -> float:
        """
        Quão bem a duração serve ao formato curto.

        Dentro da faixa ideal, nota cheia. Fora dela, cai suavemente — nunca
        zera. Um clipe excelente de 8 segundos ainda é excelente; ele só não
        ganha ponto por duração.
        """
        duration = candidate.duration_seconds
        if self.ideal_min <= duration <= self.ideal_max:
            return 100.0
        if duration < self.ideal_min:
            # 8s numa faixa que começa em 15s -> perde proporcionalmente
            return _clamp(45.0 + (duration / self.ideal_min) * 55.0)
        excess = duration - self.ideal_max
        return _clamp(100.0 - excess * 1.6)

    def originality_score(self, candidate: ClipCandidate) -> float:
        """
        Vocabulário variado como proxy fraco de originalidade.

        É proxy mesmo — por isso o peso é baixo (0.3). Melhor um sinal fraco
        e honesto que uma constante fingindo medir algo.
        """
        words = [w for w in _words(candidate.transcript) if len(w) > 3]
        if not words:
            return 40.0
        variety = len(set(words)) / len(words)
        return _clamp(35.0 + variety * 45.0)

    # ---------- agregação ----------

    def analyze_candidate(self, candidate: ClipCandidate, context: dict | None = None) -> dict:
        scores = {
            "standalone": self.standalone_score(candidate),
            "context": self.context_score(candidate),
            "hook": self.hook_score(candidate),
            "payoff": self.payoff_score(candidate),
            "ending": self.ending_score(candidate),
            "short_form_fit": self.short_form_fit(candidate),
            "emotion": self.emotion_score(candidate),
            "narrative_completeness": self.narrative_completeness(candidate),
            "originality": self.originality_score(candidate),
        }
        total_weight = sum(self.weights.values()) or 1.0
        scores["overall"] = round(
            sum(scores[k] * self.weights[k] for k in self.weights) / total_weight, 1
        )
        return scores


def analyze_all(
    candidates: list[ClipCandidate],
    analyzer: EditorialAnalyzer | None = None,
    weights: dict | None = None,
    duration_config: dict | None = None,
) -> list[ClipCandidate]:
    """Preenche heuristic_scores de cada candidato. Devolve a mesma lista."""
    engine = analyzer or HeuristicEditorialAnalyzer(weights, duration_config)
    for c in candidates:
        c.heuristic_scores = engine.analyze_candidate(c)
    return candidates
