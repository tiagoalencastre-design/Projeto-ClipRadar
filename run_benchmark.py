"""
Roda o benchmark de qualidade — Fase 2.

USO:

    python run_benchmark.py

Procura os gabaritos em data/benchmark/*.json e, pra cada um, a análise
correspondente em data/benchmark/analysis/<mesmo_nome>.json.

COMO PRODUZIR A ANÁLISE de um VOD, sem renderizar clipe nenhum:

    python -m core.pipeline --video "caminho/do/vod.mp4" --output data/benchmark/analysis/meu_vod.json

Depois copie o gabarito com o MESMO nome de arquivo em data/benchmark/.

O QUE FAZER COM O RESULTADO: anote os números antes de mexer no scoring, e
rode de novo depois. Se recall caiu, a mudança piorou — mesmo que os clipes
"pareçam" melhores num vídeo específico.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.benchmark import (
    BENCHMARK_DIR, DEFAULT_CUTOFFS, evaluate_at_cutoffs, evaluate_files,
    load_ground_truth, moments_from_analysis, summarize,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark de qualidade do ClipRadar")
    parser.add_argument("--top-n", type=int, default=10,
                        help="Quantos clipes do topo considerar (padrão: 10)")
    parser.add_argument("--overlap", type=float, default=0.3,
                        help="Sobreposição mínima pra contar acerto (padrão: 0.3)")
    parser.add_argument("--json", action="store_true",
                        help="Sai em JSON, pra comparar versões automaticamente")
    args = parser.parse_args()

    truth_files = sorted(BENCHMARK_DIR.glob("*.json"))
    if not truth_files:
        print(f"Nenhum gabarito encontrado em {BENCHMARK_DIR}/")
        print("Crie um arquivo .json com os momentos marcados à mão.")
        return 1

    results, skipped = [], []
    for truth_file in truth_files:
        analysis_file = BENCHMARK_DIR / "analysis" / truth_file.name
        if not analysis_file.exists():
            skipped.append(truth_file.name)
            continue
        try:
            results.append(evaluate_files(
                truth_file, analysis_file, top_n=args.top_n, min_overlap=args.overlap
            ))
        except (ValueError, json.JSONDecodeError) as e:
            print(f"[erro] {truth_file.name}: {e}")

    if args.json:
        print(json.dumps({
            "summary": summarize(results),
            "videos": [r.as_dict() for r in results],
        }, ensure_ascii=False, indent=2))
        return 0

    for r in results:
        print(f"\n=== {r.video} ({r.game}) ===")
        print(f"  marcados por você : {r.total_expected}")
        print(f"  encontrados no top{r.top_n}: {len(r.hits)}")
        print(f"  recall            : {r.recall_at_n:.0%}")
        print(f"  precisão          : {r.precision_at_n:.0%}")
        if r.average_rank:
            print(f"  posição média     : {r.average_rank}")
        for miss in r.missed:
            print(f"  PASSOU BATIDO     : {miss['start']:.0f}s-{miss['end']:.0f}s  {miss['label']}")

    if skipped:
        print(f"\nSem análise (rode o pipeline neles): {', '.join(skipped)}")

    # Recall e precisão em vários cortes do ranking (@5, @10, @20).
    if results and not args.json:
        print("\n" + "=" * 42)
        print("POR CORTE DO RANKING")
        acumulado: dict[str, list[float]] = {}
        for truth_file in truth_files:
            analysis_file = BENCHMARK_DIR / "analysis" / truth_file.name
            if not analysis_file.exists():
                continue
            truth = load_ground_truth(truth_file)
            analysis = json.loads(analysis_file.read_text(encoding="utf-8"))
            for chave, valor in evaluate_at_cutoffs(
                truth["moments"], moments_from_analysis(analysis),
                min_overlap=args.overlap,
            ).items():
                if valor is not None:
                    acumulado.setdefault(chave, []).append(valor)

        for n in DEFAULT_CUTOFFS:
            recall = acumulado.get(f"recall_at_{n}", [])
            precisao = acumulado.get(f"precision_at_{n}", [])
            if recall:
                print(f"  @{n:<3} recall {sum(recall)/len(recall):.0%}"
                      f"   precisão {sum(precisao)/len(precisao):.0%}")

    if results:
        s = summarize(results)
        print("\n" + "=" * 42)
        print(f"GERAL — {s['videos']} vídeo(s)")
        print(f"  recall médio   : {s['recall_at_n']:.0%}")
        print(f"  precisão média : {s['precision_at_n']:.0%}")
        print(f"  acertos        : {s['total_hits']}/{s['total_expected']}")
        print("=" * 42)
    return 0


if __name__ == "__main__":
    sys.exit(main())
