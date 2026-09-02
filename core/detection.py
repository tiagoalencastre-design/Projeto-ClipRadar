"""
Detecção de momentos candidatos num VOD.

Duas fontes de sinal, combinadas:
1. Mudanças visuais bruscas (corte de cena, troca de tela, kill-cam etc.) via PySceneDetect
2. Picos de energia de áudio (gritos, reações, tiros, explosões) via análise de RMS

Isto NÃO tenta entender "o que é uma kill" especificamente — é propositalmente agnóstico
de jogo na Fase 1. Detecção específica por jogo (ex: ler HUD de kill feed) é uma
melhoria de Fase 2+, e deve entrar como um "detector" adicional plugável, não
substituindo este.
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from pathlib import Path

from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector
import librosa


@dataclass
class RawSignal:
    """Um ponto de sinal bruto no tempo, antes de virar 'momento candidato'."""
    timestamp_seconds: float
    source: str          # "scene_cut" | "audio_peak"
    strength: float       # 0.0 - 1.0, força relativa do sinal


def detect_scene_cuts(video_path: str, threshold: float, min_scene_len_seconds: float) -> list[RawSignal]:
    """Detecta cortes de cena / mudanças visuais bruscas."""
    video = open_video(video_path)
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(
        threshold=threshold,
        min_scene_len=int(min_scene_len_seconds * video.frame_rate),
    ))
    scene_manager.detect_scenes(video)

    scene_list = scene_manager.get_scene_list()
    signals = []
    for start, _end in scene_list:
        signals.append(RawSignal(
            timestamp_seconds=start.get_seconds(),
            source="scene_cut",
            strength=1.0,  # PySceneDetect não dá magnitude por padrão; refinar depois se necessário
        ))
    return signals


def detect_audio_peaks(video_path: str, peak_sensitivity: float, window_seconds: float) -> list[RawSignal]:
    """Detecta picos de energia de áudio (RMS) acima da média — gritos, reações, ação intensa."""
    y, sr = librosa.load(video_path, sr=16000, mono=True)

    hop_length = int(sr * window_seconds)
    rms = librosa.feature.rms(y=y, frame_length=hop_length * 2, hop_length=hop_length)[0]

    mean_rms = np.mean(rms)
    std_rms = np.std(rms)
    threshold = mean_rms + peak_sensitivity * std_rms

    signals = []
    for i, value in enumerate(rms):
        if value > threshold and std_rms > 0:
            timestamp = (i * hop_length) / sr
            # normaliza a força do pico entre 0 e 1 (cap em 3 desvios-padrão pra não estourar)
            strength = min((value - mean_rms) / (3 * std_rms), 1.0)
            signals.append(RawSignal(
                timestamp_seconds=float(timestamp),
                source="audio_peak",
                strength=float(strength),
            ))
    return signals


def collect_raw_signals(video_path: str, config: dict) -> list[RawSignal]:
    """Roda todos os detectores disponíveis e retorna os sinais brutos combinados, ordenados no tempo."""
    scene_signals = detect_scene_cuts(
        video_path,
        threshold=config["scene_detection"]["threshold"],
        min_scene_len_seconds=config["scene_detection"]["min_scene_len_seconds"],
    )
    audio_signals = detect_audio_peaks(
        video_path,
        peak_sensitivity=config["audio_analysis"]["peak_sensitivity"],
        window_seconds=config["audio_analysis"]["window_seconds"],
    )
    all_signals = scene_signals + audio_signals
    return sorted(all_signals, key=lambda s: s.timestamp_seconds)
