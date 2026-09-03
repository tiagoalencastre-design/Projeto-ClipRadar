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
    Moment, evaluate, evaluate_files, load_ground_truth,
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


if __name__ == "__main__":
    unittest.main()
