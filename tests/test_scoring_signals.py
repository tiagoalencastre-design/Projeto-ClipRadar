"""
Testes dos sinais do Content Score — Fase 5.

O teste mais importante do arquivo é o último: prova que os scores dos
clipes NÃO mudaram com esta fase. Os sinais novos entram com peso 0.0, ou
seja, são calculados e ficam visíveis, mas não deslocam nenhuma escolha
até você decidir dar peso a eles.
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from core.scoring_signals import (
    SIGNALS, SignalContext, compute_new_signals, explain_signals,
)


@dataclass
class FakeSignal:
    """Imita core.detection.RawSignal sem precisar do PySceneDetect."""
    timestamp_seconds: float
    strength: float
    source: str


def _ctx(signals, start=0.0, end=30.0, excerpt="") -> SignalContext:
    return SignalContext(
        cluster=signals, transcript_excerpt=excerpt,
        start_seconds=start, end_seconds=end,
    )


class TestSignalRegistry(unittest.TestCase):
    def test_all_thirteen_requested_signals_declared(self):
        names = {s.name for s in SIGNALS}
        for requested in (
            "hook", "gameplay_intensity", "emotional_reaction", "surprise",
            "narrative_context", "retention_potential", "originality",
            "comment_potential", "share_potential", "visual_clarity",
            "ending_quality", "vertical_suitability", "viral_potential",
        ):
            self.assertIn(requested, names, f"sinal '{requested}' não declarado")

    def test_unimplemented_signals_have_no_compute(self):
        """A regra 'não inventar score sem dado' é verificável."""
        for name in ("share_potential", "vertical_suitability", "viral_potential"):
            signal = next(s for s in SIGNALS if s.name == name)
            self.assertFalse(signal.is_implemented, f"'{name}' não tem dado real")

    def test_explain_is_transparent(self):
        explained = explain_signals()
        self.assertTrue(all("description" in e and "implemented" in e for e in explained))

    def test_unimplemented_always_return_zero(self):
        result = compute_new_signals(_ctx([FakeSignal(1.0, 0.8, "audio_peak")]))
        for name in ("share_potential", "vertical_suitability", "viral_potential"):
            self.assertEqual(result[name], 0.0)


class TestAllSignalsStayInRange(unittest.TestCase):
    """Todo sinal precisa viver entre 0 e 100, ou a média pondera errado."""

    CASES = {
        "vazio": [],
        "um sinal fraco": [FakeSignal(1.0, 0.05, "audio_peak")],
        "um sinal forte": [FakeSignal(1.0, 1.0, "audio_peak")],
        "muitos cortes": [FakeSignal(i * 0.4, 0.5, "scene_cut") for i in range(50)],
        "misto": [
            FakeSignal(0.5, 0.2, "audio_peak"), FakeSignal(8.0, 0.95, "audio_peak"),
            FakeSignal(12.0, 0.6, "scene_cut"), FakeSignal(28.0, 0.9, "audio_peak"),
        ],
    }

    def test_every_signal_between_zero_and_hundred(self):
        for label, signals in self.CASES.items():
            result = compute_new_signals(_ctx(signals))
            for name, value in result.items():
                self.assertGreaterEqual(value, 0.0, f"{name} negativo em '{label}'")
                self.assertLessEqual(value, 100.0, f"{name} acima de 100 em '{label}'")


class TestHook(unittest.TestCase):
    def test_early_strong_signal_scores_higher_than_late(self):
        cedo = compute_new_signals(_ctx([FakeSignal(1.0, 0.9, "audio_peak")]))["hook"]
        tarde = compute_new_signals(_ctx([FakeSignal(25.0, 0.9, "audio_peak")]))["hook"]
        self.assertGreater(cedo, tarde)

    def test_empty_cluster_is_zero(self):
        self.assertEqual(compute_new_signals(_ctx([]))["hook"], 0.0)


class TestSurprise(unittest.TestCase):
    def test_jump_beats_constant_loudness(self):
        """Surpresa é mudança, não volume."""
        salto = compute_new_signals(_ctx([
            FakeSignal(1.0, 0.1, "audio_peak"), FakeSignal(5.0, 0.95, "audio_peak"),
        ]))["surprise"]
        constante = compute_new_signals(_ctx([
            FakeSignal(1.0, 0.9, "audio_peak"), FakeSignal(5.0, 0.9, "audio_peak"),
        ]))["surprise"]
        self.assertGreater(salto, constante)

    def test_single_signal_has_no_surprise(self):
        self.assertEqual(
            compute_new_signals(_ctx([FakeSignal(1.0, 0.9, "audio_peak")]))["surprise"],
            0.0,
        )


class TestVisualClarity(unittest.TestCase):
    def test_moderate_cutting_beats_static_and_chaotic(self):
        estatico = compute_new_signals(_ctx([FakeSignal(1.0, 0.5, "audio_peak")]))["visual_clarity"]
        moderado = compute_new_signals(_ctx(
            [FakeSignal(i * 5.0, 0.5, "scene_cut") for i in range(4)]
        ))["visual_clarity"]
        caotico = compute_new_signals(_ctx(
            [FakeSignal(i * 0.3, 0.5, "scene_cut") for i in range(90)]
        ))["visual_clarity"]
        self.assertGreater(moderado, estatico)
        self.assertGreater(moderado, caotico)


class TestEndingQuality(unittest.TestCase):
    def test_strong_ending_beats_fading_out(self):
        forte = compute_new_signals(_ctx([
            FakeSignal(2.0, 0.3, "audio_peak"), FakeSignal(28.0, 0.95, "audio_peak"),
        ]))["ending_quality"]
        fraco = compute_new_signals(_ctx([
            FakeSignal(2.0, 0.95, "audio_peak"), FakeSignal(5.0, 0.2, "audio_peak"),
        ]))["ending_quality"]
        self.assertGreater(forte, fraco)


class TestScoresDidNotChange(unittest.TestCase):
    """
    A garantia central da Fase 5: nenhum clipe muda de posição.
    Com peso 0.0, os sinais novos são calculados mas não pontuam.
    """

    def _breakdown(self):
        from core.scoring import ContentScoreBreakdown
        return ContentScoreBreakdown(
            gameplay_intensity=80.0, emotional_reaction=90.0,
            narrative_context=60.0, retention_potential=70.0, originality=60.0,
            hook=95.0, surprise=88.0, visual_clarity=77.0, ending_quality=91.0,
        )

    OLD_WEIGHTS = {
        "gameplay_intensity": 1.0, "emotional_reaction": 1.0,
        "narrative_context": 0.8, "retention_potential": 1.0,
        "originality": 0.6, "chat_reaction": 0.0, "comment_potential": 0.0,
    }

    def test_zero_weight_signals_do_not_change_score(self):
        breakdown = self._breakdown()
        antes = breakdown.weighted_total(self.OLD_WEIGHTS)
        novos = dict(self.OLD_WEIGHTS)
        novos.update({
            "hook": 0.0, "surprise": 0.0, "visual_clarity": 0.0,
            "ending_quality": 0.0, "share_potential": 0.0,
            "vertical_suitability": 0.0, "viral_potential": 0.0,
        })
        self.assertEqual(breakdown.weighted_total(novos), antes)

    def test_raising_a_weight_does_change_the_score(self):
        """E quando você DECIDIR usar, funciona."""
        breakdown = self._breakdown()
        antes = breakdown.weighted_total(self.OLD_WEIGHTS)
        com_hook = dict(self.OLD_WEIGHTS, hook=1.0)
        self.assertNotEqual(breakdown.weighted_total(com_hook), antes)

    def test_unknown_weight_key_is_ignored_not_crashing(self):
        """Typo no settings.yaml não pode derrubar a análise."""
        breakdown = self._breakdown()
        com_typo = dict(self.OLD_WEIGHTS, hoook=1.0)
        self.assertEqual(
            breakdown.weighted_total(com_typo),
            breakdown.weighted_total(self.OLD_WEIGHTS),
        )


if __name__ == "__main__":
    unittest.main()
