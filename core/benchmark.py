"""
Benchmark de qualidade da detecção — Fase 2.

PARA QUE SERVE: hoje não existe forma de saber se uma mudança no scoring
melhorou ou piorou a escolha dos momentos. Você olha alguns clipes e tem uma
impressão. Impressão não detecta regressão.

COMO FUNCIONA: você marca à mão os momentos bons de alguns VODs (o
"gabarito"). O benchmark compara o que o ClipRadar escolheu com o que você
marcou, e devolve números comparáveis entre versões.

FORMATO DO GABARITO (data/benchmark/<nome>.json):

    {
      "video": "live_valorant_01.mp4",
      "game": "valorant",
      "moments": [
        {"start": 124.0, "end": 152.0, "label": "clutch 1v3"},
        {"start": 401.5, "end": 420.0, "label": "reação"}
      ]
    }

O "label" é só pra você se orientar depois; o cálculo usa start/end.

MÉTRICAS, e por que estas:

    recall_at_n  — dos momentos que você marcou, quantos apareceram entre
                   os N primeiros do ranking. É A MÉTRICA QUE IMPORTA: o
                   usuário só olha os primeiros clipes.

    precision_at_n — dos N primeiros que o sistema escolheu, quantos eram
                   de verdade. Mede quanto lixo o usuário vê.

    rank_of_hits — em que posição cada acerto apareceu. Um sistema que acha
                   tudo mas coloca o melhor em 15º lugar não presta.

    missed       — o que passou batido. É onde estão as ideias de melhoria.

Nada aqui depende de FFmpeg ou de IA: o benchmark lê o analysis JSON que o
pipeline já produz.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

BENCHMARK_DIR = Path("data/benchmark")

# Quanto dois trechos precisam se sobrepor pra contar como o mesmo momento.
# 0.3 = 30% de sobreposição. Frouxo de propósito: se o sistema pegou o
# clutch mas começou 4 segundos antes, ainda é um acerto.
DEFAULT_OVERLAP = 0.3


@dataclass(frozen=True)
class Moment:
    start: float
    end: float
    label: str = ""

    @property
    def duration(self) -> float:
        return max(self.end - self.start, 0.0)


@dataclass
class BenchmarkResult:
    video: str
    game: str
    top_n: int
    total_expected: int
    hits: list[dict] = field(default_factory=list)
    missed: list[dict] = field(default_factory=list)
    false_positives: int = 0

    @property
    def recall_at_n(self) -> float:
        if not self.total_expected:
            return 0.0
        return round(len(self.hits) / self.total_expected, 3)

    @property
    def precision_at_n(self) -> float:
        detected = len(self.hits) + self.false_positives
        if not detected:
            return 0.0
        return round(len(self.hits) / detected, 3)

    @property
    def average_rank(self) -> float | None:
        """Posição média dos acertos. Quanto menor, melhor."""
        if not self.hits:
            return None
        return round(sum(h["rank"] for h in self.hits) / len(self.hits), 2)

    def as_dict(self) -> dict:
        return {
            "video": self.video,
            "game": self.game,
            "top_n": self.top_n,
            "total_expected": self.total_expected,
            "hits": len(self.hits),
            "missed": len(self.missed),
            "false_positives": self.false_positives,
            "recall_at_n": self.recall_at_n,
            "precision_at_n": self.precision_at_n,
            "average_rank": self.average_rank,
            "missed_details": self.missed,
        }


def overlap_ratio(a: Moment, b: Moment) -> float:
    """
    Quanto dois trechos se sobrepõem, relativo ao MENOR dos dois.

    Usar o menor é proposital: se o sistema gerou um clipe de 60s que contém
    inteiro o seu momento marcado de 15s, isso é um acerto — mesmo que a
    sobreposição seja só 25% do clipe grande.
    """
    start = max(a.start, b.start)
    end = min(a.end, b.end)
    intersection = max(end - start, 0.0)
    if intersection <= 0:
        return 0.0
    smaller = min(a.duration, b.duration)
    if smaller <= 0:
        return 0.0
    return intersection / smaller


def load_ground_truth(path: str | Path) -> dict:
    """Lê um gabarito. Erro de formato vira mensagem clara, não traceback."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "moments" not in data:
        raise ValueError(f"{path}: falta a lista 'moments'.")
    moments = []
    for i, m in enumerate(data["moments"]):
        if "start" not in m or "end" not in m:
            raise ValueError(f"{path}: momento {i} sem 'start' ou 'end'.")
        moments.append(Moment(float(m["start"]), float(m["end"]), m.get("label", "")))
    return {
        "video": data.get("video", Path(path).stem),
        "game": data.get("game", "desconhecido"),
        "moments": moments,
    }


def moments_from_analysis(analysis: dict) -> list[Moment]:
    """
    Converte o analysis.json do pipeline em momentos, JÁ ORDENADOS por score.

    Usa context_start_seconds quando existe, porque é onde o clipe realmente
    começa depois do Context Builder.
    """
    raw = sorted(analysis.get("moments", []), key=lambda m: m.get("score", 0), reverse=True)
    return [
        Moment(
            start=float(m.get("context_start_seconds", m.get("start_seconds", 0))),
            end=float(m.get("end_seconds", 0)),
            label=m.get("clip_id", ""),
        )
        for m in raw
    ]


def evaluate(
    expected: list[Moment],
    detected: list[Moment],
    video: str = "",
    game: str = "",
    top_n: int = 10,
    min_overlap: float = DEFAULT_OVERLAP,
) -> BenchmarkResult:
    """
    Compara o gabarito com o que o sistema escolheu.

    `detected` precisa vir ORDENADO por score (melhor primeiro) — é o que
    moments_from_analysis já faz.
    """
    top = detected[:top_n]
    result = BenchmarkResult(
        video=video, game=game, top_n=top_n, total_expected=len(expected)
    )

    matched_detected: set[int] = set()

    for want in expected:
        best_rank, best_ratio = None, 0.0
        for rank, got in enumerate(top, start=1):
            ratio = overlap_ratio(want, got)
            if ratio >= min_overlap and ratio > best_ratio:
                best_rank, best_ratio = rank, ratio

        if best_rank is None:
            result.missed.append({
                "start": want.start, "end": want.end, "label": want.label,
            })
        else:
            matched_detected.add(best_rank - 1)
            result.hits.append({
                "label": want.label, "rank": best_rank,
                "overlap": round(best_ratio, 3),
            })

    result.false_positives = len(top) - len(matched_detected)
    return result


def evaluate_files(
    ground_truth_path: str | Path,
    analysis_path: str | Path,
    top_n: int = 10,
    min_overlap: float = DEFAULT_OVERLAP,
) -> BenchmarkResult:
    """Atalho: lê os dois arquivos e compara."""
    truth = load_ground_truth(ground_truth_path)
    analysis = json.loads(Path(analysis_path).read_text(encoding="utf-8"))
    return evaluate(
        expected=truth["moments"],
        detected=moments_from_analysis(analysis),
        video=truth["video"], game=truth["game"],
        top_n=top_n, min_overlap=min_overlap,
    )


def summarize(results: list[BenchmarkResult]) -> dict:
    """
    Média entre vários vídeos — o número que você compara entre versões.

    A média é simples (não ponderada por quantidade de momentos) de
    propósito: um VOD com 20 momentos marcados não deve dominar o resultado
    de outro com 3.
    """
    if not results:
        return {"videos": 0, "recall_at_n": 0.0, "precision_at_n": 0.0}
    return {
        "videos": len(results),
        "recall_at_n": round(sum(r.recall_at_n for r in results) / len(results), 3),
        "precision_at_n": round(sum(r.precision_at_n for r in results) / len(results), 3),
        "total_expected": sum(r.total_expected for r in results),
        "total_hits": sum(len(r.hits) for r in results),
        "total_missed": sum(len(r.missed) for r in results),
    }
