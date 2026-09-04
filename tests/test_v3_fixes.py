"""
Testes das correções da V3.

Cada bloco corresponde a um defeito CONCRETO encontrado na auditoria, com
o comportamento antigo documentado no comentário.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from core.candidates import ClipCandidate
from core.detection import RawSignal
from core.discovery import _candidate_budget, _trim_evenly, discover_and_select
from core.editorial import HeuristicEditorialAnalyzer
from core.montage import _resolve_cut_points
from core.transcription import TranscriptSegment

CONFIG = yaml.safe_load(Path("config/settings.yaml").read_text(encoding="utf-8"))


def seg(a, b, text):
    return TranscriptSegment(start_seconds=a, end_seconds=b, text=text)


def sig(t, s=0.8):
    return RawSignal(timestamp_seconds=t, source="audio_peak", strength=s)


def long_vod(moments: int = 90, spacing: int = 120, strength: float = 0.9):
    """VOD sintético com momentos distribuídos ao longo de horas."""
    signals, transcript = [], []
    for i in range(moments):
        base = 100 + i * spacing
        signals += [sig(base, strength * 0.7), sig(base + 8, strength), sig(base + 14, strength * 0.9)]
        transcript += [
            seg(base - 4, base + 4, "ontem eu tava jogando ranked com meus amigos"),
            seg(base + 6, base + 12, "aí eu consegui pegar todos sozinho"),
            seg(base + 13, base + 20, "não acredito que deu certo"),
        ]
    return signals, transcript


# ============================================================
# CRÍTICO — o limite global ignorava o resto do vídeo
# ============================================================

class TestFullVideoCoverage(unittest.TestCase):
    def test_long_vod_is_analyzed_to_the_end(self):
        """
        ANTES: o laço parava ao bater 100 candidatos. Num VOD de 3 horas,
        só os primeiros 20 minutos eram analisados — em silêncio.
        """
        signals, transcript = long_vod()
        final, _ = discover_and_select(signals, transcript, CONFIG, verbose=False)
        last_minute = max(c.start_seconds for c in final) / 60
        self.assertGreater(last_minute, 120, "a análise ainda para no começo do vídeo")

    def test_clips_are_spread_across_the_video(self):
        signals, transcript = long_vod()
        final, _ = discover_and_select(signals, transcript, CONFIG, verbose=False)
        minutes = sorted(c.start_seconds / 60 for c in final)
        first_half = sum(1 for m in minutes if m < 90)
        second_half = len(minutes) - first_half
        self.assertGreater(second_half, 0, "nenhum clipe da segunda metade")
        self.assertLessEqual(abs(first_half - second_half), len(minutes) * 0.6)

    def test_budget_scales_with_duration(self):
        cfg = {"max_candidates_per_hour": 60, "absolute_max_candidates": 600}
        short = _candidate_budget(600, cfg)      # 10 minutos
        long = _candidate_budget(10800, cfg)     # 3 horas
        self.assertLess(short, long)

    def test_budget_has_a_floor_and_a_ceiling(self):
        cfg = {"max_candidates_per_hour": 60, "absolute_max_candidates": 600}
        self.assertGreaterEqual(_candidate_budget(30, cfg), 20)
        self.assertLessEqual(_candidate_budget(360000, cfg), 600)

    def test_trim_keeps_candidates_from_every_part(self):
        """Cortar por nota global concentraria tudo no trecho mais barulhento."""
        candidates = [
            ClipCandidate(candidate_id=f"c{i}", story_id=f"s{i}",
                          candidate_type="MOMENT",
                          start_seconds=i * 100, end_seconds=i * 100 + 30)
            for i in range(100)
        ]
        kept = _trim_evenly(candidates, 10)
        self.assertEqual(len(kept), 10)
        self.assertLess(min(c.start_seconds for c in kept), 1000)
        self.assertGreater(max(c.start_seconds for c in kept), 8000)

    def test_trim_is_a_noop_when_under_the_limit(self):
        candidates = [
            ClipCandidate(candidate_id="c", story_id="s", candidate_type="MOMENT",
                          start_seconds=0, end_seconds=10)
        ]
        self.assertEqual(_trim_evenly(candidates, 50), candidates)


# ============================================================
# ALTO — Edit Plan definia pontos que não chegavam ao corte
# ============================================================

class TestEditPlanReachesTheCut(unittest.TestCase):
    MOMENT = {"context_start_seconds": 100.0, "end_seconds": 140.0}

    def test_without_a_plan_uses_the_engine_boundaries(self):
        self.assertEqual(_resolve_cut_points(self.MOMENT, None, None, None), (100.0, 140.0))

    def test_plan_points_are_applied(self):
        """ANTES: hook_point e exit_point eram calculados e ignorados."""
        plan = {"hook_point": 104.0, "exit_point": 132.0}
        self.assertEqual(_resolve_cut_points(self.MOMENT, plan, None, None), (104.0, 132.0))

    def test_absurd_plan_falls_back_to_the_engine(self):
        """Um ponto fora do momento cortaria um trecho errado do vídeo."""
        plan = {"hook_point": 900.0, "exit_point": 950.0}
        self.assertEqual(_resolve_cut_points(self.MOMENT, plan, None, None), (100.0, 140.0))

    def test_user_override_wins_over_the_plan(self):
        plan = {"hook_point": 104.0}
        start, _ = _resolve_cut_points(self.MOMENT, plan, 110.0, None)
        self.assertEqual(start, 110.0)

    def test_inverted_plan_does_not_produce_a_negative_clip(self):
        plan = {"hook_point": 139.0, "exit_point": 101.0}
        start, end = _resolve_cut_points(self.MOMENT, plan, None, None)
        self.assertGreater(end, start)

    def test_non_numeric_plan_values_are_ignored(self):
        plan = {"hook_point": "cedo", "exit_point": None}
        self.assertEqual(_resolve_cut_points(self.MOMENT, plan, None, None), (100.0, 140.0))


# ============================================================
# Item 14 — modo AUTO
# ============================================================

class TestAutoClipCount(unittest.TestCase):
    def test_good_video_yields_more_than_a_weak_one(self):
        """Um vídeo fraco não deve render 10 clipes ruins."""
        good_signals, good_transcript = long_vod(20, strength=0.95)
        weak_signals, weak_transcript = [], []
        for i in range(20):
            base = 100 + i * 120
            weak_signals += [sig(base, 0.12), sig(base + 8, 0.15)]
            weak_transcript += [seg(base - 2, base + 6, "ele"), seg(base + 7, base + 12, "isso")]

        good, _ = discover_and_select(good_signals, good_transcript, CONFIG, verbose=False)
        weak, _ = discover_and_select(weak_signals, weak_transcript, CONFIG, verbose=False)
        self.assertGreater(len(good), len(weak))

    def test_weak_video_still_returns_something(self):
        """Melhor pouca coisa boa do que uma tela vazia."""
        signals, transcript = [], []
        for i in range(10):
            base = 100 + i * 120
            signals += [sig(base, 0.1)]
            transcript += [seg(base - 2, base + 6, "isso")]
        final, _ = discover_and_select(signals, transcript, CONFIG, verbose=False)
        self.assertGreaterEqual(len(final), 1)

    def test_fixed_number_is_still_supported(self):
        config = {**CONFIG, "selection": {**CONFIG["selection"], "max_final_clips": 5}}
        signals, transcript = long_vod(30)
        final, _ = discover_and_select(signals, transcript, config, verbose=False)
        self.assertLessEqual(len(final), 5)

    def test_report_says_when_auto_was_used(self):
        signals, transcript = long_vod(20)
        _, report = discover_and_select(signals, transcript, CONFIG, verbose=False)
        self.assertTrue(report.as_dict()["auto_mode"])


# ============================================================
# Item 8/10 — duração adaptativa e adequação a short-form
# ============================================================

class TestShortFormFit(unittest.TestCase):
    def setUp(self):
        self.engine = HeuristicEditorialAnalyzer(
            duration_config={"ideal_min_seconds": 15, "ideal_max_seconds": 45})

    def _clip(self, duration):
        return ClipCandidate(candidate_id="c", story_id="s", candidate_type="MOMENT",
                             start_seconds=0, end_seconds=duration)

    def test_ideal_range_scores_full(self):
        for duration in (15, 30, 45):
            self.assertEqual(self.engine.short_form_fit(self._clip(duration)), 100.0)

    def test_too_short_and_too_long_score_lower(self):
        self.assertLess(self.engine.short_form_fit(self._clip(5)), 100.0)
        self.assertLess(self.engine.short_form_fit(self._clip(90)), 100.0)

    def test_never_zero(self):
        """Um clipe excelente de 8s ainda é excelente — só não ganha ponto aqui."""
        self.assertGreater(self.engine.short_form_fit(self._clip(6)), 0.0)

    def test_it_is_a_signal_not_a_rule(self):
        """A duração continua saindo do conteúdo: o peso é modesto."""
        self.assertLess(self.engine.weights["short_form_fit"], 1.0)

    def test_durations_still_vary(self):
        signals, transcript = long_vod(20)
        final, _ = discover_and_select(signals, transcript, CONFIG, verbose=False)
        durations = {round(c.duration_seconds) for c in final}
        self.assertGreater(len(durations), 1, "todos os clipes saíram com a mesma duração")


# ============================================================
# Item 22/27 — nenhuma configuração morta
# ============================================================

class TestNoDeadConfiguration(unittest.TestCase):
    def test_every_yaml_key_is_read_by_the_code(self):
        """Config que não é lida é mentira: o usuário ajusta e nada muda."""
        import os

        source = "".join(
            Path(f"core/{f}").read_text(encoding="utf-8")
            for f in os.listdir("core") if f.endswith(".py")
        )

        def keys(node):
            for key, value in (node or {}).items():
                yield key
                if isinstance(value, dict):
                    yield from keys(value)

        dead = [
            key for key in set(keys(CONFIG))
            if f'"{key}"' not in source and f"'{key}'" not in source
        ]
        self.assertEqual(dead, [], f"configuração sem efeito: {sorted(dead)}")


# ============================================================
# Item 30 — end-to-end com FFmpeg real
# ============================================================

@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg não instalado")
class TestEndToEndRender(unittest.TestCase):
    """Renderiza de verdade. 'O programa abriu' não é validação (item 30)."""

    def test_renders_a_playable_vertical_clip(self):
        from core.montage import VERTICAL_RES, VIDEO_OUTPUT_ARGS, append_watermark
        from core.montage import _build_blur_background_filter

        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "src.mp4"
            output = Path(folder) / "out.mp4"

            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", "testsrc2=size=1920x1080:rate=30:duration=3",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(source),
            ], capture_output=True, check=True)

            filter_complex = append_watermark(
                _build_blur_background_filter(VERTICAL_RES), VERTICAL_RES)
            subprocess.run([
                "ffmpeg", "-y", "-i", str(source),
                "-filter_complex", filter_complex, "-map", "[__stacked]",
                "-t", "2", *[a for a in VIDEO_OUTPUT_ARGS if a != "-c:a" ][:8],
                "-an", str(output),
            ], capture_output=True, check=True)

            self.assertTrue(output.exists())

            probe = subprocess.run([
                "ffprobe", "-v", "error", "-select_streams", "v",
                "-show_entries", "stream=width,height,pix_fmt",
                "-of", "csv=p=0", str(output),
            ], capture_output=True, text=True, check=True)
            self.assertIn("1080,1920", probe.stdout)
            self.assertIn("yuv420p", probe.stdout, "formato que players não abrem")

            # Decodifica o arquivo inteiro: pega timestamps quebrados.
            decode = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(output), "-f", "null", "-"],
                capture_output=True, text=True,
            )
            self.assertEqual(decode.stderr.strip(), "", "arquivo com erro de decodificação")


if __name__ == "__main__":
    unittest.main()
