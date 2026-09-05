"""
Testes do benchmark de qualidade — Fase 2.

Sem FFmpeg, sem Whisper, sem internet: tudo é feito com números.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.benchmark import (
    DEFAULT_CUTOFFS, Moment, evaluate_at_cutoffs, evaluate, evaluate_files, load_ground_truth,
    moments_from_analysis, overlap_ratio, summarize,
)


class TestOverlap(unittest.TestCase):
    def test_identical_is_total(self):
        self.assertEqual(overlap_ratio(Moment(10, 20), Moment(10, 20)), 1.0)

    def test_no_intersection_is_zero(self):
        self.assertEqual(overlap_ratio(Moment(10, 20), Moment(30, 40)), 0.0)

    def test_touching_edges_is_zero(self):
        self.assertEqual(overlap_ratio(Moment(10, 20), Moment(20, 30)), 0.0)

    def test_contained_moment_counts_as_full(self):
        """Clipe grande contendo o momento marcado é acerto, não meio acerto."""
        self.assertEqual(overlap_ratio(Moment(10, 25), Moment(0, 60)), 1.0)

    def test_partial_overlap(self):
        # marcado 10-20 (10s), detectado 15-25 -> 5s em comum sobre 10s
        self.assertAlmostEqual(overlap_ratio(Moment(10, 20), Moment(15, 25)), 0.5)

    def test_zero_duration_does_not_crash(self):
        self.assertEqual(overlap_ratio(Moment(10, 10), Moment(5, 20)), 0.0)


class TestEvaluate(unittest.TestCase):
    EXPECTED = [
        Moment(100, 130, "clutch"),
        Moment(400, 420, "reação"),
        Moment(900, 940, "engraçado"),
    ]

    def test_perfect_detection(self):
        detected = [Moment(100, 130), Moment(400, 420), Moment(900, 940)]
        r = evaluate(self.EXPECTED, detected, top_n=10)
        self.assertEqual(r.recall_at_n, 1.0)
        self.assertEqual(r.precision_at_n, 1.0)
        self.assertEqual(r.missed, [])

    def test_nothing_detected(self):
        r = evaluate(self.EXPECTED, [], top_n=10)
        self.assertEqual(r.recall_at_n, 0.0)
        self.assertEqual(len(r.missed), 3)

    def test_missed_moments_are_reported_with_labels(self):
        """O que passou batido é onde estão as ideias de melhoria."""
        detected = [Moment(100, 130)]
        r = evaluate(self.EXPECTED, detected, top_n=10)
        labels = {m["label"] for m in r.missed}
        self.assertEqual(labels, {"reação", "engraçado"})

    def test_rank_is_recorded(self):
        detected = [Moment(5000, 5010), Moment(6000, 6010), Moment(100, 130)]
        r = evaluate(self.EXPECTED, detected, top_n=10)
        self.assertEqual(r.hits[0]["rank"], 3)
        self.assertEqual(r.average_rank, 3.0)

    def test_top_n_cuts_the_ranking(self):
        """Achar em 8º não vale se o usuário só vê os 3 primeiros."""
        detected = [Moment(5000 + i * 100, 5010 + i * 100) for i in range(7)]
        detected.append(Moment(100, 130))
        self.assertEqual(evaluate(self.EXPECTED, detected, top_n=3).recall_at_n, 0.0)
        self.assertGreater(evaluate(self.EXPECTED, detected, top_n=10).recall_at_n, 0.0)

    def test_false_positives_counted(self):
        detected = [Moment(100, 130), Moment(5000, 5030), Moment(6000, 6030)]
        r = evaluate(self.EXPECTED, detected, top_n=3)
        self.assertEqual(r.false_positives, 2)
        self.assertAlmostEqual(r.precision_at_n, 1 / 3, places=2)

    def test_loose_overlap_still_counts(self):
        """Começar alguns segundos antes não deve virar erro."""
        detected = [Moment(96, 126)]  # marcado era 100-130
        r = evaluate(self.EXPECTED, detected, top_n=5)
        self.assertEqual(len(r.hits), 1)

    def test_no_expected_moments_does_not_crash(self):
        r = evaluate([], [Moment(1, 2)], top_n=5)
        self.assertEqual(r.recall_at_n, 0.0)

    def test_average_rank_is_none_without_hits(self):
        self.assertIsNone(evaluate(self.EXPECTED, [], top_n=5).average_rank)


class TestAnalysisConversion(unittest.TestCase):
    ANALYSIS = {
        "moments": [
            {"clip_id": "A", "score": 5.0, "context_start_seconds": 10, "end_seconds": 40},
            {"clip_id": "B", "score": 9.0, "context_start_seconds": 100, "end_seconds": 130},
            {"clip_id": "C", "score": 7.0, "start_seconds": 200, "end_seconds": 230},
        ]
    }

    def test_sorted_by_score_descending(self):
        moments = moments_from_analysis(self.ANALYSIS)
        self.assertEqual([m.label for m in moments], ["B", "C", "A"])

    def test_falls_back_to_start_seconds(self):
        moments = moments_from_analysis(self.ANALYSIS)
        self.assertEqual(moments[1].start, 200)

    def test_empty_analysis(self):
        self.assertEqual(moments_from_analysis({}), [])


class TestGroundTruthFile(unittest.TestCase):
    def _write(self, data: dict) -> Path:
        tmp = Path(tempfile.mkdtemp()) / "gabarito.json"
        tmp.write_text(json.dumps(data), encoding="utf-8")
        return tmp

    def test_loads_valid_file(self):
        path = self._write({
            "video": "live.mp4", "game": "valorant",
            "moments": [{"start": 10, "end": 20, "label": "ace"}],
        })
        truth = load_ground_truth(path)
        self.assertEqual(truth["game"], "valorant")
        self.assertEqual(truth["moments"][0].label, "ace")

    def test_missing_moments_gives_clear_error(self):
        path = self._write({"video": "x.mp4"})
        with self.assertRaises(ValueError) as ctx:
            load_ground_truth(path)
        self.assertIn("moments", str(ctx.exception))

    def test_moment_without_end_gives_clear_error(self):
        path = self._write({"moments": [{"start": 10}]})
        with self.assertRaises(ValueError) as ctx:
            load_ground_truth(path)
        self.assertIn("end", str(ctx.exception))

    def test_evaluate_files_end_to_end(self):
        folder = Path(tempfile.mkdtemp())
        truth = folder / "gabarito.json"
        truth.write_text(json.dumps({
            "video": "live.mp4", "game": "valorant",
            "moments": [{"start": 100, "end": 130, "label": "clutch"}],
        }), encoding="utf-8")
        analysis = folder / "analysis.json"
        analysis.write_text(json.dumps({
            "moments": [{"clip_id": "A", "score": 9.0,
                         "context_start_seconds": 98, "end_seconds": 132}],
        }), encoding="utf-8")

        result = evaluate_files(truth, analysis, top_n=5)
        self.assertEqual(result.recall_at_n, 1.0)
        self.assertEqual(result.game, "valorant")


class TestSummary(unittest.TestCase):
    def test_averages_across_videos(self):
        a = evaluate([Moment(10, 20)], [Moment(10, 20)], top_n=5)
        b = evaluate([Moment(10, 20), Moment(50, 60)], [Moment(10, 20)], top_n=5)
        summary = summarize([a, b])
        self.assertEqual(summary["videos"], 2)
        self.assertEqual(summary["total_expected"], 3)
        self.assertEqual(summary["total_hits"], 2)
        self.assertAlmostEqual(summary["recall_at_n"], 0.75, places=2)

    def test_empty_summary_does_not_crash(self):
        self.assertEqual(summarize([])["videos"], 0)

    def test_result_as_dict_is_json_serializable(self):
        r = evaluate([Moment(10, 20, "x")], [Moment(50, 60)], top_n=5)
        json.dumps(r.as_dict())


class TestOneToOneMatching(unittest.TestCase):
    """
    Um candidato só pode responder por UM momento esperado.

    O BUG QUE ISTO CORRIGE: antes, cada momento procurava seu melhor
    candidato de forma independente. Um clipe longo cobrindo três momentos
    marcados contava como três acertos — 100% de recall com um clipe só.
    O benchmark premiava justamente o defeito que a V2 veio corrigir.
    """

    EXPECTED = [
        Moment(110, 125, "clutch"),
        Moment(140, 155, "reação"),
        Moment(175, 190, "risada"),
    ]

    def test_one_long_clip_does_not_cover_three_moments(self):
        result = evaluate(self.EXPECTED, [Moment(100, 200, "único")], top_n=10)
        self.assertEqual(len(result.hits), 1)
        self.assertEqual(len(result.missed), 2)
        self.assertLess(result.recall_at_n, 0.5)

    def test_separate_clips_score_full_recall(self):
        detected = [Moment(108, 127), Moment(138, 157), Moment(173, 192)]
        result = evaluate(self.EXPECTED, detected, top_n=10)
        self.assertEqual(result.recall_at_n, 1.0)
        self.assertEqual(len(result.hits), 3)

    def test_each_rank_is_used_at_most_once(self):
        result = evaluate(self.EXPECTED, [Moment(100, 200)], top_n=10)
        ranks = [h["rank"] for h in result.hits]
        self.assertEqual(len(ranks), len(set(ranks)))

    def test_best_overlap_wins_the_pairing(self):
        """Quando as coberturas diferem, fica com a melhor — não com a primeira."""
        expected = [Moment(100, 130, "alvo")]
        detected = [
            Moment(120, 200, "parcial"),   # cobre só o fim do momento
            Moment(101, 129, "justo"),     # cobre quase tudo
        ]
        result = evaluate(expected, detected, top_n=10)
        self.assertEqual(len(result.hits), 1)
        self.assertEqual(result.hits[0]["rank"], 2, "pareou com o pior candidato")

    def test_equal_overlap_is_decided_by_rank(self):
        """
        Empate de cobertura é resolvido pelo melhor rank — o candidato que o
        sistema julgou melhor. Sem esse desempate, o resultado dependeria da
        ordem em que os candidatos aparecem na lista.
        """
        expected = [Moment(100, 130, "alvo")]
        detected = [Moment(100, 400, "largo"), Moment(100, 130, "exato")]
        result = evaluate(expected, detected, top_n=10)
        self.assertEqual(result.hits[0]["rank"], 1)

    def test_result_does_not_depend_on_ground_truth_order(self):
        """Reordenar o gabarito não pode mudar a nota."""
        detected = [Moment(108, 127), Moment(138, 157), Moment(173, 192)]
        direct = evaluate(self.EXPECTED, detected, top_n=10)
        reversed_truth = evaluate(list(reversed(self.EXPECTED)), detected, top_n=10)
        self.assertEqual(direct.recall_at_n, reversed_truth.recall_at_n)
        self.assertEqual(
            sorted(h["rank"] for h in direct.hits),
            sorted(h["rank"] for h in reversed_truth.hits),
        )

    def test_false_positives_count_unmatched_clips(self):
        result = evaluate(self.EXPECTED, [Moment(100, 200), Moment(900, 950)], top_n=10)
        self.assertEqual(result.false_positives, 1)

    def test_hits_are_reported_in_rank_order(self):
        detected = [Moment(173, 192), Moment(108, 127), Moment(138, 157)]
        result = evaluate(self.EXPECTED, detected, top_n=10)
        ranks = [h["rank"] for h in result.hits]
        self.assertEqual(ranks, sorted(ranks))


class TestCutoffMetrics(unittest.TestCase):
    def _scenario(self):
        expected = [Moment(i * 200 + 50, i * 200 + 80, f"m{i}") for i in range(8)]
        # Ordenação imperfeita: dois bons momentos caem fora do top 5.
        detected = [Moment(i * 200 + 48, i * 200 + 82) for i in (0, 1, 7, 3, 2, 5, 4, 6)]
        return expected, detected

    def test_reports_every_cutoff(self):
        metrics = evaluate_at_cutoffs(*self._scenario())
        for n in DEFAULT_CUTOFFS:
            self.assertIn(f"recall_at_{n}", metrics)
            self.assertIn(f"precision_at_{n}", metrics)

    def test_recall_grows_with_the_cutoff(self):
        """Olhar mais fundo no ranking nunca pode achar menos."""
        m = evaluate_at_cutoffs(*self._scenario())
        self.assertLessEqual(m["recall_at_5"], m["recall_at_10"])
        self.assertLessEqual(m["recall_at_10"], m["recall_at_20"])

    def test_separates_detection_from_ordering(self):
        """
        recall@20 alto com recall@5 baixo significa que o sistema ACHA os
        momentos e ORDENA mal — problema bem diferente de não achar nada.
        """
        m = evaluate_at_cutoffs(*self._scenario())
        self.assertEqual(m["recall_at_20"], 1.0)
        self.assertLess(m["recall_at_5"], 1.0)


if __name__ == "__main__":
    unittest.main()
