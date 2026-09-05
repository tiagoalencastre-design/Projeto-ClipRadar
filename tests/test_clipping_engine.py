"""
Testes do motor de clipping reconstruído.

Cada bloco corresponde a um defeito CONCRETO da auditoria. Vários testes
comparam com o comportamento antigo, que está descrito no comentário.

Nada aqui usa FFmpeg, Whisper, IA ou internet.
"""
from __future__ import annotations

import unittest

from core.boundaries import detect_boundaries
from core.dedup import deduplicate, rank_with_diversity, text_similarity, time_overlap
from core.detection import RawSignal
from core.events import ACTION, CLUTCH, LAUGHTER, REACTION, Event, build_events, classify
from core.story import Story, build_stories
from core.transcription import TranscriptSegment


def sig(t: float, strength: float = 0.8, source: str = "audio_peak") -> RawSignal:
    return RawSignal(timestamp_seconds=t, source=source, strength=strength)


def seg(start: float, end: float, text: str) -> TranscriptSegment:
    return TranscriptSegment(start_seconds=start, end_seconds=end, text=text)


# ============================================================
# CRÍTICO 1 — clustering encadeado
# ============================================================

class TestChainClusteringFixed(unittest.TestCase):
    def test_long_busy_stretch_is_not_one_event(self):
        """
        ANTES: sinais a cada 4s ao longo de 3 minutos viravam UM cluster de
        176 segundos, porque o intervalo era medido a partir do ÚLTIMO sinal.
        """
        signals = [sig(t) for t in range(100, 280, 4)]
        events = build_events(signals, [], window_seconds=6.0)
        self.assertGreater(len(events), 10, "voltou a encadear")
        self.assertLess(max(e.duration for e in events), 10.0)

    def test_window_measured_from_group_start(self):
        # 0, 5, 10: cada um a 5s do anterior, mas 10 está a 10s do início.
        events = build_events([sig(0), sig(5), sig(10)], [], window_seconds=6.0)
        self.assertEqual(len(events), 2)

    def test_close_signals_still_group(self):
        events = build_events([sig(0), sig(1), sig(2)], [], window_seconds=6.0)
        self.assertEqual(len(events), 1)

    def test_no_signals_gives_no_events(self):
        self.assertEqual(build_events([], []), [])


# ============================================================
# ALTO 6 — "mano"/"cara" geravam hype falso
# ============================================================

class TestClassification(unittest.TestCase):
    def test_filler_words_are_not_reaction(self):
        """'mano' e 'cara' aparecem em quase toda frase em português."""
        category, confidence = classify("mano que jogo cara", 0.5, has_speech=True)
        self.assertNotEqual(category, REACTION)
        self.assertLess(confidence, 0.4)

    def test_real_reaction_is_detected(self):
        category, confidence = classify(
            "não acredito que peguei isso!", 0.9, has_speech=True
        )
        self.assertEqual(category, REACTION)
        self.assertGreater(confidence, 0.6)

    def test_laughter(self):
        category, _ = classify("kkkkk morri de rir", 0.6, has_speech=True)
        self.assertEqual(category, LAUGHTER)

    def test_no_speech_becomes_action_or_unknown(self):
        self.assertEqual(classify("", 0.9, has_speech=False)[0], ACTION)
        self.assertEqual(classify("", 0.2, has_speech=False)[0], "unknown")

    def test_confidence_never_reaches_certainty(self):
        """Heurística de palavra-chave não merece certeza total."""
        _, confidence = classify(
            "clutch clutch clutch 1v5 sozinho peguei todos", 1.0, has_speech=True
        )
        self.assertLessEqual(confidence, 0.9)


# ============================================================
# Item 22 do briefing — A+B mesma história, C independente
# ============================================================

class TestStoryGrouping(unittest.TestCase):
    def test_briefing_scenario_a_plus_b_and_separate_c(self):
        """
        O caso pedido explicitamente: A e B pertencem à mesma história,
        C é independente. Esperado: CLIP A+B e CLIP C — nunca A+B+C.
        """
        transcript = [
            seg(99, 104, "agora vai"),
            seg(106, 111, "não acredito que peguei"),
            seg(150, 156, "olha esse round"),
        ]
        events = [
            Event(100, 104, ACTION, 0.7, 0.5),
            Event(106, 110, REACTION, 0.95, 0.8),
            Event(150, 155, CLUTCH, 0.9, 0.8),
        ]
        stories = build_stories(events, transcript, max_silence_seconds=4.0)
        self.assertEqual(len(stories), 2)
        self.assertEqual(len(stories[0].events), 2)
        self.assertEqual(len(stories[1].events), 1)

    def test_two_clutches_are_two_stories(self):
        """Proximidade não junta dois acontecimentos fortes do mesmo tipo."""
        events = [Event(100, 104, CLUTCH, 0.9, 0.8), Event(106, 110, CLUTCH, 0.9, 0.8)]
        stories = build_stories(events, [seg(99, 111, "falando sem parar")])
        self.assertEqual(len(stories), 2)

    def test_long_silence_splits(self):
        events = [Event(100, 104, ACTION, 0.7, 0.5), Event(112, 116, REACTION, 0.9, 0.8)]
        stories = build_stories(events, [], max_silence_seconds=4.0)
        self.assertEqual(len(stories), 2)

    def test_single_event_is_a_valid_story(self):
        stories = build_stories([Event(100, 104, CLUTCH, 0.9, 0.8)], [])
        self.assertEqual(len(stories), 1)

    def test_story_reports_payoff_and_reaction(self):
        story = Story(events=[Event(100, 104, ACTION, 0.7, 0.5),
                              Event(106, 110, REACTION, 0.9, 0.8)])
        self.assertTrue(story.has_payoff_and_reaction)

    def test_main_category_is_the_strongest_event(self):
        story = Story(events=[Event(100, 104, ACTION, 0.4, 0.3),
                              Event(106, 110, CLUTCH, 0.95, 0.85)])
        self.assertEqual(story.main_category, CLUTCH)


# ============================================================
# CRÍTICO 2 — duração era aritmética, não conteúdo
# ============================================================

class TestBoundaries(unittest.TestCase):
    TRANSCRIPT = [
        seg(94, 99, "tô tentando isso faz cinco minutos"),
        seg(100, 104, "agora vai"),
        seg(106, 112, "não acredito que peguei"),
    ]

    def _story(self):
        return Story(events=[Event(100, 104, ACTION, 0.7, 0.5),
                             Event(106, 110, REACTION, 0.95, 0.8)])

    def test_starts_at_a_sentence_start(self):
        b = detect_boundaries(self._story(), self.TRANSCRIPT)
        self.assertEqual(b.hook_seconds, 94.0)

    def test_ends_at_a_sentence_end(self):
        b = detect_boundaries(self._story(), self.TRANSCRIPT)
        self.assertEqual(b.exit_seconds, 112.0)

    def test_payoff_is_the_strongest_event_not_the_last(self):
        story = Story(events=[Event(100, 104, CLUTCH, 0.95, 0.9),
                              Event(106, 110, REACTION, 0.5, 0.5)])
        b = detect_boundaries(story, self.TRANSCRIPT)
        self.assertLess(b.payoff_seconds, 106)

    def test_duration_varies_with_content(self):
        """Duração é consequência: histórias diferentes dão durações diferentes."""
        short = detect_boundaries(
            Story(events=[Event(100, 102, ACTION, 0.8, 0.5)]),
            [seg(99, 103, "olha isso")],
        )
        long = detect_boundaries(self._story(), self.TRANSCRIPT)
        self.assertNotEqual(round(short.duration), round(long.duration))

    def test_minimum_is_protection_not_target(self):
        b = detect_boundaries(
            Story(events=[Event(100, 101, ACTION, 0.8, 0.5)]), [], min_seconds=5.0
        )
        self.assertGreaterEqual(b.duration, 5.0)

    def test_maximum_preserves_the_payoff(self):
        """Ao cortar por duração, o payoff não pode ficar de fora."""
        story = Story(events=[Event(100, 105, ACTION, 0.9, 0.5)])
        b = detect_boundaries(story, [], max_seconds=10.0)
        self.assertLessEqual(b.duration, 10.0)
        self.assertGreaterEqual(b.payoff_seconds, b.hook_seconds)
        self.assertLessEqual(b.payoff_seconds, b.exit_seconds)

    def test_works_without_transcript(self):
        b = detect_boundaries(Story(events=[Event(100, 104, ACTION, 0.8, 0.5)]), [])
        self.assertGreater(b.duration, 0)


# ============================================================
# CRÍTICO 4 — supressão temporal apagava independentes
# ============================================================

class TestDeduplication(unittest.TestCase):
    def test_independent_moment_15s_later_survives(self):
        """
        ANTES: qualquer candidato a menos de 15s de um aceito era apagado.
        Sua reação engraçada logo depois do clutch sumia.
        """
        clutch = {"context_start_seconds": 100, "end_seconds": 130, "score": 9.0,
                  "transcript_excerpt": "peguei todos sozinho"}
        reaction = {"context_start_seconds": 145, "end_seconds": 160, "score": 7.0,
                    "transcript_excerpt": "kkkk não acredito nisso"}
        self.assertEqual(len(deduplicate([clutch, reaction])), 2)

    def test_overlapping_coverage_is_removed(self):
        a = {"context_start_seconds": 100, "end_seconds": 130, "score": 9.0,
             "transcript_excerpt": "clutch"}
        b = {"context_start_seconds": 105, "end_seconds": 128, "score": 6.0,
             "transcript_excerpt": "clutch"}
        kept = deduplicate([a, b])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["score"], 9.0, "manteve o pior dos dois")

    def test_same_speech_is_redundant(self):
        a = {"context_start_seconds": 100, "end_seconds": 130, "score": 9.0,
             "transcript_excerpt": "peguei todos sozinho nesse round insano"}
        b = {"context_start_seconds": 125, "end_seconds": 150, "score": 8.0,
             "transcript_excerpt": "peguei todos sozinho nesse round insano"}
        self.assertEqual(len(deduplicate([a, b])), 1)

    def test_text_similarity_ignores_stopwords(self):
        low = text_similarity("o que é para", "a de que para")
        self.assertLess(low, 0.5)

    def test_time_overlap_of_contained_clip(self):
        self.assertEqual(time_overlap(10, 25, 0, 60), 1.0)

    def test_empty_list(self):
        self.assertEqual(deduplicate([]), [])


# ============================================================
# Item 11 — diversidade
# ============================================================

class TestDiversity(unittest.TestCase):
    def _moments(self):
        m = [{"score": 9 - i * 0.1, "category": "clutch",
              "context_start_seconds": i * 100, "end_seconds": i * 100 + 30,
              "transcript_excerpt": ""} for i in range(5)]
        m.append({"score": 7.0, "category": "laughter",
                  "context_start_seconds": 900, "end_seconds": 930,
                  "transcript_excerpt": ""})
        return m

    def test_variety_beats_pure_ranking(self):
        categories = [m["category"] for m in rank_with_diversity(self._moments(), 3)]
        self.assertIn("laughter", categories)

    def test_zero_weight_reproduces_old_behaviour(self):
        categories = [
            m["category"]
            for m in rank_with_diversity(self._moments(), 3, diversity_weight=0)
        ]
        self.assertEqual(categories, ["clutch"] * 3)

    def test_best_clip_still_comes_first(self):
        ranked = rank_with_diversity(self._moments(), 3)
        self.assertEqual(ranked[0]["score"], 9.0)

    def test_respects_max_clips(self):
        self.assertEqual(len(rank_with_diversity(self._moments(), 2)), 2)


# ============================================================
# Item 9 — story completeness com peso significativo
# ============================================================

class TestStoryCompleteness(unittest.TestCase):
    def test_complete_story_scores_higher_than_bare_peak(self):
        from core.legacy.scoring import _story_completeness

        transcript = [seg(94, 99, "faz cinco minutos tentando"),
                      seg(100, 104, "agora vai"),
                      seg(106, 112, "não acredito")]
        complete = Story(events=[Event(100, 104, ACTION, 0.7, 0.5),
                                 Event(106, 110, REACTION, 0.9, 0.8)])
        bare = Story(events=[Event(500, 502, ACTION, 0.95, 0.4)])

        complete_score = _story_completeness(
            complete, detect_boundaries(complete, transcript))
        bare_score = _story_completeness(bare, detect_boundaries(bare, []))
        self.assertGreater(complete_score, bare_score)

    def test_weight_is_significant_in_settings(self):
        """O briefing pede peso significativo — não simbólico."""
        import yaml
        from pathlib import Path
        # Os pesos deste motor moraram no topo do YAML até serem movidos
        # para a seção "legacy". A asserção é a mesma; só o caminho mudou.
        weights = yaml.safe_load(
            Path("config/settings.yaml").read_text(encoding="utf-8")
        )["legacy"]["content_score_weights"]
        self.assertGreaterEqual(weights["story_completeness"], 1.0)

    def test_phase5_signals_are_active_now(self):
        """hook/surprise/ending eram calculados e ignorados (peso 0)."""
        import yaml
        from pathlib import Path
        # Os pesos deste motor moraram no topo do YAML até serem movidos
        # para a seção "legacy". A asserção é a mesma; só o caminho mudou.
        weights = yaml.safe_load(
            Path("config/settings.yaml").read_text(encoding="utf-8")
        )["legacy"]["content_score_weights"]
        for name in ("hook", "surprise", "ending_quality"):
            self.assertGreater(weights[name], 0.0, f"{name} continua ignorado")


if __name__ == "__main__":
    unittest.main()
