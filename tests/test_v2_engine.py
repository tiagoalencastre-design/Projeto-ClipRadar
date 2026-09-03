"""
Testes do motor V2 — múltiplos candidatos por história.

Nenhuma IA, nenhuma rede, nenhum FFmpeg. Tudo local e determinístico.
"""
from __future__ import annotations

import unittest

import yaml
from pathlib import Path

from core.candidates import (
    CONTEXTUAL, FULL_STORY, HOOK_PAYOFF, MOMENT, PAYOFF_REACTION,
    REACTION_ONLY, ClipCandidate, generate_candidates,
)
from core.dedup import deduplicate_candidates, same_content, select_with_diversity
from core.detection import RawSignal
from core.discovery import discover_and_select
from core.editorial import (
    EditorialAnalyzer, HeuristicEditorialAnalyzer, analyze_all,
)
from core.events import ACTION, CLUTCH, LAUGHTER, REACTION, Event
from core.story import Story
from core.transcription import TranscriptSegment


def seg(a, b, text):
    return TranscriptSegment(start_seconds=a, end_seconds=b, text=text)


def sig(t, strength=0.8):
    return RawSignal(timestamp_seconds=t, source="audio_peak", strength=strength)


def candidate(**kw) -> ClipCandidate:
    base = dict(
        candidate_id="c1", story_id="s1", candidate_type=FULL_STORY,
        start_seconds=100.0, end_seconds=130.0, transcript="", category="action",
        payoff_seconds=115.0, signals={"intensity": 0.8},
    )
    base.update(kw)
    return ClipCandidate(**base)


CONFIG = yaml.safe_load(Path("config/settings.yaml").read_text(encoding="utf-8"))


# ============================================================
# §4 e §5 — uma Story gera VÁRIOS candidatos
# ============================================================

class TestCandidateGeneration(unittest.TestCase):
    TRANSCRIPT = [
        seg(90, 96, "ontem eu tava jogando com meus amigos"),
        seg(97, 103, "e eu quase fui banido por causa disso"),
        seg(104, 110, "aí eu consegui pegar todos sozinho"),
        seg(112, 118, "não acredito que deu certo"),
    ]

    def _story(self):
        return Story(events=[
            Event(100, 106, ACTION, 0.6, 0.5),
            Event(108, 112, CLUTCH, 0.95, 0.85),
            Event(113, 117, REACTION, 0.9, 0.8),
        ])

    def test_one_story_produces_multiple_candidates(self):
        """A mudança central do V2: Story != 1 clipe."""
        cands = generate_candidates(self._story(), self.TRANSCRIPT)
        self.assertGreater(len(cands), 1, "voltou a ser 1 candidato por história")

    def test_different_types_are_produced(self):
        types = {c.candidate_type for c in generate_candidates(self._story(), self.TRANSCRIPT)}
        self.assertGreaterEqual(len(types), 2)

    def test_candidates_have_different_durations(self):
        durations = {
            round(c.duration_seconds)
            for c in generate_candidates(self._story(), self.TRANSCRIPT)
        }
        self.assertGreater(len(durations), 1, "todos os recortes ficaram iguais")

    def test_near_identical_candidates_are_dropped(self):
        cands = generate_candidates(self._story(), self.TRANSCRIPT)
        for a, b in zip(cands, cands[1:]):
            same = (abs(a.start_seconds - b.start_seconds) < 2.0
                    and abs(a.end_seconds - b.end_seconds) < 2.0)
            self.assertFalse(same)

    def test_single_event_story_still_produces_a_candidate(self):
        """Nunca perder uma história por não conseguir recortá-la."""
        story = Story(events=[Event(200, 204, CLUTCH, 0.9, 0.8)])
        self.assertGreaterEqual(len(generate_candidates(story, self.TRANSCRIPT)), 1)

    def test_candidate_carries_data_for_future_ai(self):
        """§23: a estrutura precisa comportar o que uma IA futura receberia."""
        c = generate_candidates(self._story(), self.TRANSCRIPT)[0]
        d = c.as_dict()
        for field in ("candidate_id", "story_id", "candidate_type",
                      "start", "end", "duration", "category", "scores", "selection"):
            self.assertIn(field, d)


# ============================================================
# §16, §17, §18 — standalone, contexto e referências órfãs
# ============================================================

class TestEditorialHeuristics(unittest.TestCase):
    def setUp(self):
        self.engine = HeuristicEditorialAnalyzer()

    def test_orphan_reference_at_start_is_penalized(self):
        """'Ele fez isso' sem sabermos quem é 'ele'."""
        orphan = candidate(transcript="ele fez isso e aquilo lá")
        clear = candidate(transcript="ontem eu tava jogando com meus amigos e consegui")
        self.assertGreater(
            self.engine.standalone_score(clear),
            self.engine.standalone_score(orphan),
        )

    def test_narrative_opener_softens_the_penalty(self):
        hard = self.engine.orphan_reference_penalty(candidate(transcript="ele isso aquilo"))
        soft = self.engine.orphan_reference_penalty(
            candidate(transcript="então ele fez isso quando eu tava jogando"))
        self.assertLess(soft, hard)

    def test_context_quality_beats_context_duration(self):
        """§10: dez segundos de muleta não explicam nada."""
        filler = candidate(transcript="mano olha isso caraca tipo assim mano cara")
        real = candidate(transcript="ontem eu tava jogando ranked e o cara me reportou")
        self.assertGreater(self.engine.context_score(real), self.engine.context_score(filler))

    def test_hook_works_without_loud_audio(self):
        """§9: 'quase fui banido' é hook mesmo em volume normal."""
        quiet_strong = candidate(
            transcript="eu quase fui banido por causa disso",
            signals={"intensity": 0.2})
        loud_empty = candidate(transcript="mano cara tipo", signals={"intensity": 0.9})
        self.assertGreater(
            self.engine.hook_score(quiet_strong), self.engine.hook_score(loud_empty) * 0.7
        )

    def test_payoff_recognized_without_volume(self):
        """§11: punchline é payoff sem pico de áudio."""
        c = candidate(transcript="e no final eu consegui ganhar", signals={"intensity": 0.1})
        self.assertGreater(self.engine.payoff_score(c), 40.0)

    def test_payoff_outside_the_cut_is_penalized(self):
        outside = candidate(payoff_seconds=500.0)
        inside = candidate(payoff_seconds=115.0)
        self.assertGreater(self.engine.payoff_score(inside), self.engine.payoff_score(outside))

    def test_ending_on_sentence_end_scores_higher(self):
        good = candidate(boundary_reason="termina no fim da frase", end_seconds=120.0)
        bad = candidate(boundary_reason="corte curto após o payoff", end_seconds=120.0)
        self.assertGreater(self.engine.ending_score(good), self.engine.ending_score(bad))

    def test_reaction_only_is_penalized_for_standalone(self):
        alone = candidate(candidate_type=REACTION_ONLY, transcript="não acredito")
        full = candidate(candidate_type=FULL_STORY, transcript="não acredito")
        self.assertGreater(
            self.engine.standalone_score(full), self.engine.standalone_score(alone)
        )

    def test_all_scores_in_range(self):
        for text in ("", "mano", "ontem eu tava jogando e consegui ganhar tudo!"):
            scores = self.engine.analyze_candidate(candidate(transcript=text))
            for name, value in scores.items():
                self.assertGreaterEqual(value, 0.0, name)
                self.assertLessEqual(value, 100.0, name)

    def test_overall_is_produced(self):
        self.assertIn("overall", self.engine.analyze_candidate(candidate()))


# ============================================================
# §22, §33 — interface pronta pra IA, sem IA
# ============================================================

class TestAnalyzerInterface(unittest.TestCase):
    def test_heuristic_implements_the_contract(self):
        self.assertIsInstance(HeuristicEditorialAnalyzer(), EditorialAnalyzer)

    def test_a_custom_analyzer_can_replace_it(self):
        """Prova que trocar o analisador não exige mexer no resto."""
        class FakeAnalyzer(EditorialAnalyzer):
            name = "fake"

            def analyze_candidate(self, candidate, context=None):
                return {"overall": 99.0}

        cands = analyze_all([candidate()], FakeAnalyzer())
        self.assertEqual(cands[0].heuristic_scores["overall"], 99.0)

    def test_no_network_or_ai_dependency(self):
        """§34: nada de OpenAI, requests ou httpx neste módulo."""
        source = Path("core/editorial.py").read_text(encoding="utf-8")
        for forbidden in ("openai", "requests", "httpx", "anthropic", "api_key"):
            self.assertNotIn(forbidden, source.lower())


# ============================================================
# §19 — dedup semântico que preserva propostas diferentes
# ============================================================

class TestSemanticDedup(unittest.TestCase):
    def test_same_payoff_similar_cut_is_duplicate(self):
        a = candidate(start_seconds=100, end_seconds=130, payoff_seconds=115,
                      transcript="peguei todos sozinho")
        b = candidate(start_seconds=102, end_seconds=131, payoff_seconds=115,
                      transcript="peguei todos sozinho")
        self.assertTrue(same_content(a, b)[0])

    def test_different_editorial_proposals_coexist(self):
        """§19: FULL_STORY de 40s e PAYOFF_REACTION de 12s são leituras distintas."""
        full = candidate(candidate_type=FULL_STORY, start_seconds=100,
                         end_seconds=140, payoff_seconds=132)
        short = candidate(candidate_type=PAYOFF_REACTION, start_seconds=128,
                          end_seconds=140, payoff_seconds=132)
        self.assertFalse(same_content(full, short)[0])

    def test_distant_candidates_are_never_duplicates(self):
        a = candidate(start_seconds=100, end_seconds=130)
        b = candidate(start_seconds=900, end_seconds=930)
        self.assertFalse(same_content(a, b)[0])

    def test_dedup_keeps_the_best_scored(self):
        a = candidate(start_seconds=100, end_seconds=130, payoff_seconds=115)
        b = candidate(start_seconds=101, end_seconds=129, payoff_seconds=115)
        a.heuristic_scores = {"overall": 90}
        b.heuristic_scores = {"overall": 50}
        kept = deduplicate_candidates([b, a])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].heuristic_scores["overall"], 90)


# ============================================================
# §20 — diversidade de categoria e temporal
# ============================================================

class TestDiversitySelection(unittest.TestCase):
    def _many(self):
        out = []
        for i in range(6):
            c = candidate(candidate_id=f"c{i}", category="clutch",
                          start_seconds=100 + i * 10, end_seconds=130 + i * 10)
            c.heuristic_scores = {"overall": 90 - i}
            out.append(c)
        funny = candidate(candidate_id="f", category="laughter",
                          start_seconds=2000, end_seconds=2030)
        funny.heuristic_scores = {"overall": 70}
        out.append(funny)
        return out

    def test_category_variety_is_considered(self):
        chosen = select_with_diversity(self._many(), max_clips=3)
        self.assertIn("laughter", [c.category for c in chosen])

    def test_temporal_spread_is_considered(self):
        chosen = select_with_diversity(self._many(), max_clips=3)
        starts = sorted(c.start_seconds for c in chosen)
        self.assertGreater(starts[-1] - starts[0], 100)

    def test_diversity_is_a_factor_not_a_rule(self):
        """Um VOD pode ter vários clipes do mesmo tipo se forem excelentes."""
        chosen = select_with_diversity(self._many(), max_clips=5)
        self.assertGreaterEqual(
            sum(1 for c in chosen if c.category == "clutch"), 2
        )

    def test_selection_reason_is_recorded(self):
        chosen = select_with_diversity(self._many(), max_clips=2)
        self.assertTrue(all(c.selected and c.selection_reason for c in chosen))


# ============================================================
# §30 — teste principal do V2
# ============================================================

class TestV2MainScenario(unittest.TestCase):
    """
    VOD com 5 histórias distintas. O sistema deve descobrir bem mais
    candidatos que histórias, e selecionar vários clipes — provando que
    uma Story não limita mais o sistema a um único clipe.
    """

    def _vod(self):
        signals, transcript = [], []
        stories = [
            (100, "ontem eu tava jogando ranked com os meus amigos",
                  "aí eu consegui pegar todos sozinho", "não acredito que deu certo"),
            (400, "olha o que aconteceu aqui nesse round",
                  "e eu perdi tudo de novo", "kkkkk morri de rir"),
            (800, "eu quase fui banido por causa disso",
                  "então eu descobri o problema", "no final resolvi sozinho"),
            (1200, "vocês não sabem o que aconteceu ontem",
                   "aí que veio a parte boa", "consegui ganhar no último segundo"),
            (1700, "deixa eu contar uma coisa rápida",
                   "o problema foi que ninguém avisou", "acabou dando certo"),
        ]
        for base, a, b, c in stories:
            signals += [sig(base, 0.6), sig(base + 8, 0.95), sig(base + 14, 0.85)]
            transcript += [
                seg(base - 4, base + 4, a),
                seg(base + 6, base + 12, b),
                seg(base + 13, base + 20, c),
            ]
        return signals, transcript

    def test_discovers_more_candidates_than_stories(self):
        signals, transcript = self._vod()
        final, report = discover_and_select(signals, transcript, CONFIG, verbose=False)
        self.assertGreater(
            report.raw_candidates, report.stories,
            "cada história ainda está virando um único candidato",
        )

    def test_produces_several_clips(self):
        signals, transcript = self._vod()
        final, _ = discover_and_select(signals, transcript, CONFIG, verbose=False)
        self.assertGreaterEqual(len(final), 3)
        self.assertLessEqual(len(final), 10)

    def test_report_tracks_every_stage(self):
        """§31: dá pra responder 'por que esse clipe não apareceu?'"""
        signals, transcript = self._vod()
        _, report = discover_and_select(signals, transcript, CONFIG, verbose=False)
        d = report.as_dict()
        for stage in ("events", "stories", "raw_candidates",
                      "after_score_floor", "after_dedup", "final"):
            self.assertIn(stage, d)
        self.assertGreaterEqual(report.raw_candidates, report.after_dedup)
        self.assertGreaterEqual(report.after_dedup, report.final)

    def test_selected_clips_have_varied_durations(self):
        signals, transcript = self._vod()
        final, _ = discover_and_select(signals, transcript, CONFIG, verbose=False)
        durations = {round(c.duration_seconds) for c in final}
        self.assertGreater(len(durations), 1)

    def test_durations_respect_absolute_limits(self):
        signals, transcript = self._vod()
        final, _ = discover_and_select(signals, transcript, CONFIG, verbose=False)
        for c in final:
            self.assertGreaterEqual(c.duration_seconds, 3.0)
            self.assertLessEqual(c.duration_seconds, 80.0)

    def test_empty_input_does_not_crash(self):
        final, report = discover_and_select([], [], CONFIG, verbose=False)
        self.assertEqual(final, [])
        self.assertEqual(report.final, 0)

    def test_every_candidate_has_a_selection_reason(self):
        signals, transcript = self._vod()
        final, _ = discover_and_select(signals, transcript, CONFIG, verbose=False)
        self.assertTrue(all(c.selection_reason for c in final))


if __name__ == "__main__":
    unittest.main()
