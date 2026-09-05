"""
Testes de INTEGRAÇÃO do pipeline de produção com a V2.

O que estes testes provam (§26 da spec): quando um vídeo é processado
normalmente pelo aplicativo, o resultado vem do motor V2 — e não do
caminho antigo.

Não usam FFmpeg, Whisper, IA nem internet: a transcrição e os sinais são
fornecidos direto, e só a camada de decisão é exercitada.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import yaml

from core.candidates import ClipCandidate
from core.detection import RawSignal
from core.discovery import discover_and_select
from core.transcription import TranscriptSegment
from core.v2_adapter import candidates_to_moments

CONFIG = yaml.safe_load(Path("config/settings.yaml").read_text(encoding="utf-8"))


def seg(a, b, text):
    return TranscriptSegment(start_seconds=a, end_seconds=b, text=text)


def sig(t, s=0.8):
    return RawSignal(timestamp_seconds=t, source="audio_peak", strength=s)


def vod_with_five_stories():
    """VOD sintético: 5 histórias distintas, bem separadas no tempo."""
    stories = [
        (100, "ontem eu tava jogando ranked com os meus amigos",
              "aí eu consegui pegar todos sozinho", "não acredito que deu certo"),
        (400, "olha o que aconteceu nesse round aqui",
              "e eu perdi tudo de novo", "kkkkk morri de rir"),
        (800, "eu quase fui banido por causa disso",
              "então eu descobri qual era o problema", "no final resolvi sozinho"),
        (1200, "vocês não sabem o que aconteceu ontem",
               "aí que veio a parte boa", "consegui ganhar no último segundo"),
        (1700, "deixa eu contar uma coisa rápida pra vocês",
               "o problema foi que ninguém avisou", "acabou dando certo"),
    ]
    signals, transcript = [], []
    for base, a, b, c in stories:
        signals += [sig(base, 0.6), sig(base + 8, 0.95), sig(base + 14, 0.85)]
        transcript += [
            seg(base - 4, base + 4, a),
            seg(base + 6, base + 12, b),
            seg(base + 13, base + 20, c),
        ]
    return signals, transcript


# ============================================================
# §26 — o pipeline real usa a V2
# ============================================================

class TestPipelineUsesV2(unittest.TestCase):
    SOURCE = Path("core/pipeline.py").read_text(encoding="utf-8")

    def test_pipeline_imports_discovery(self):
        self.assertIn("from core.discovery import discover_and_select", self.SOURCE)

    def test_pipeline_calls_discover_and_select(self):
        self.assertIn("discover_and_select(signals, transcript, config)", self.SOURCE)

    def test_pipeline_no_longer_calls_the_old_engine(self):
        """O ponto crítico da tarefa."""
        calls = re.findall(r"^\s*\w*\s*=?\s*build_candidate_moments\(", self.SOURCE, re.M)
        self.assertEqual(calls, [], "o pipeline voltou a usar o motor antigo")

    def test_pipeline_does_not_import_the_old_engine(self):
        """
        O motor antigo mudou de lugar (core/scoring.py -> core/legacy/).
        Verificamos OS DOIS caminhos: se checássemos só o novo, um import do
        caminho antigo passaria batido; se checássemos só o antigo, o teste
        viraria decoração depois da mudança.
        """
        for forbidden in (
            "from core.scoring import build_candidate_moments",
            "from core.legacy.scoring import build_candidate_moments",
            "from core.legacy import scoring",
        ):
            self.assertNotIn(forbidden, self.SOURCE, f"pipeline importou: {forbidden}")


# ============================================================
# §3 e §4 — uma única autoridade de seleção
# ============================================================

class TestSingleSelectionAuthority(unittest.TestCase):
    MONTAGE = Path("core/montage.py").read_text(encoding="utf-8")

    def test_montage_does_not_rank_by_diversity_anymore(self):
        """A diversidade acontece uma vez só, no discovery."""
        self.assertNotIn("rank_with_diversity", self.MONTAGE)

    def test_montage_does_not_filter_by_score_threshold(self):
        """score_floor/score_gap não podem mais cortar clipes aqui."""
        self.assertNotIn("threshold = max(score_floor", self.MONTAGE)

    def test_compatibility_layer_is_documented(self):
        self.assertIn("CAMADA DE COMPATIBILIDADE", self.MONTAGE)

    def test_montage_preserves_everything_it_receives(self):
        """Sem cortar por nota: o que a V2 selecionou é o que é renderizado."""
        from core.montage import select_moments_automatically

        moments = [
            {"clip_id": f"C{i}", "score": 10.0 + i, "start_seconds": i * 100,
             "end_seconds": i * 100 + 30, "context_start_seconds": i * 100}
            for i in range(8)
        ]
        kept = select_moments_automatically(moments, max_moments=20)
        self.assertEqual(len(kept), 8)

    def test_montage_respects_the_quantity_cap(self):
        from core.montage import select_moments_automatically

        moments = [
            {"clip_id": f"C{i}", "score": 10.0 + i, "start_seconds": i * 100,
             "end_seconds": i * 100 + 30, "context_start_seconds": i * 100}
            for i in range(8)
        ]
        self.assertEqual(len(select_moments_automatically(moments, max_moments=3)), 3)

    def test_montage_returns_chronological_order(self):
        from core.montage import select_moments_automatically

        moments = [
            {"clip_id": "B", "score": 50, "start_seconds": 900,
             "end_seconds": 930, "context_start_seconds": 900},
            {"clip_id": "A", "score": 90, "start_seconds": 100,
             "end_seconds": 130, "context_start_seconds": 100},
        ]
        kept = select_moments_automatically(moments, max_moments=10)
        self.assertEqual([m["clip_id"] for m in kept], ["A", "B"])


# ============================================================
# §5 — compatibilidade do analysis.json
# ============================================================

class TestAnalysisFormatCompatibility(unittest.TestCase):
    def _moments(self):
        signals, transcript = vod_with_five_stories()
        selected, _ = discover_and_select(signals, transcript, CONFIG, verbose=False)
        return candidates_to_moments(selected, transcript), transcript

    def test_old_keys_are_present(self):
        """O front-end e o montage.py leem estas chaves — não podem sumir."""
        moments, _ = self._moments()
        for m in moments:
            for key in ("clip_id", "score", "start_seconds", "end_seconds",
                        "context_start_seconds", "transcript_excerpt",
                        "breakdown", "transcript_segments", "transcript_words"):
                self.assertIn(key, m, f"chave antiga '{key}' sumiu")

    def test_new_v2_keys_are_added_alongside(self):
        moments, _ = self._moments()
        for m in moments:
            for key in ("candidate_id", "story_id", "candidate_type",
                        "scores", "selection_reason", "payoff_seconds"):
                self.assertIn(key, m)

    def test_breakdown_keeps_the_keys_the_frontend_reads(self):
        moments, _ = self._moments()
        breakdown = moments[0]["breakdown"]
        for key in ("gameplay_intensity", "emotional_reaction",
                    "narrative_context", "retention_potential", "hook"):
            self.assertIn(key, breakdown)

    def test_result_is_json_serializable(self):
        moments, _ = self._moments()
        json.dumps(moments)

    def test_montage_can_consume_the_adapted_moments(self):
        """Prova de ponta: o formato da V2 passa pelo montage sem erro."""
        from core.montage import select_moments_automatically

        moments, _ = self._moments()
        kept = select_moments_automatically(moments, max_moments=10)
        self.assertGreater(len(kept), 0)
        for m in kept:
            self.assertIn("clip_id", m)


# ============================================================
# §24 — teste de integração obrigatório
# ============================================================

class TestIntegrationScenario(unittest.TestCase):
    def test_raw_candidates_and_multiple_final_clips(self):
        signals, transcript = vod_with_five_stories()
        final, report = discover_and_select(signals, transcript, CONFIG, verbose=False)
        self.assertGreaterEqual(report.raw_candidates, 8)
        self.assertGreater(len(final), 1)

    def test_a_single_story_can_produce_more_than_one_candidate(self):
        signals, transcript = vod_with_five_stories()
        _, report = discover_and_select(signals, transcript, CONFIG, verbose=False)
        self.assertTrue(
            any(n > 1 for n in report.per_story),
            "nenhuma história gerou mais de um candidato",
        )

    def test_clips_come_from_different_stories(self):
        """§18: preferir espalhar entre histórias a concentrar numa só."""
        signals, transcript = vod_with_five_stories()
        final, _ = discover_and_select(signals, transcript, CONFIG, verbose=False)
        self.assertGreater(len({c.story_id for c in final}), 1)

    def test_report_covers_every_stage(self):
        signals, transcript = vod_with_five_stories()
        _, report = discover_and_select(signals, transcript, CONFIG, verbose=False)
        d = report.as_dict()
        for stage in ("events", "stories", "raw_candidates", "valid_candidates",
                      "after_score_floor", "after_dedup", "final"):
            self.assertIn(stage, d)

    def test_funnel_never_grows(self):
        signals, transcript = vod_with_five_stories()
        _, r = discover_and_select(signals, transcript, CONFIG, verbose=False)
        self.assertGreaterEqual(r.raw_candidates, r.valid_candidates)
        self.assertGreaterEqual(r.valid_candidates, r.after_score_floor)
        self.assertGreaterEqual(r.after_score_floor, r.after_dedup)
        self.assertGreaterEqual(r.after_dedup, r.final)

    def test_not_limited_to_six(self):
        signals, transcript = vod_with_five_stories()
        _, report = discover_and_select(signals, transcript, CONFIG, verbose=False)
        self.assertGreater(report.raw_candidates, 6)


# ============================================================
# §9 — story_max separado de clip_max
# ============================================================

class TestStoryVersusClipDuration(unittest.TestCase):
    def test_settings_separate_the_two_limits(self):
        self.assertIn("story", CONFIG)
        self.assertIn("story_max_duration_seconds", CONFIG["story"])
        self.assertIn("absolute_max_seconds", CONFIG["clip_duration"])

    def test_story_limit_is_larger_than_clip_limit(self):
        """A história é o contexto; o clipe é um recorte dela."""
        self.assertGreater(
            CONFIG["story"]["story_max_duration_seconds"],
            CONFIG["clip_duration"]["absolute_max_seconds"],
        )


# ============================================================
# Regra absoluta — nenhuma IA
# ============================================================

class TestNoAIInThePipeline(unittest.TestCase):
    V2_MODULES = ("core/discovery.py", "core/candidates.py",
                  "core/editorial.py", "core/v2_adapter.py")

    def test_no_ai_imports_in_v2_modules(self):
        for module in self.V2_MODULES:
            source = Path(module).read_text(encoding="utf-8").lower()
            for forbidden in ("openai", "anthropic", "httpx", "requests",
                              "omniroute", "api_key"):
                self.assertNotIn(forbidden, source, f"{module} tocou em {forbidden}")

    def test_the_default_analyzer_is_heuristic(self):
        from core.editorial import HeuristicEditorialAnalyzer, analyze_all

        c = ClipCandidate(candidate_id="c", story_id="s", candidate_type="MOMENT",
                          start_seconds=0, end_seconds=10)
        analyze_all([c])
        self.assertIn("overall", c.heuristic_scores)
        self.assertEqual(HeuristicEditorialAnalyzer().name, "heuristic")


if __name__ == "__main__":
    unittest.main()
