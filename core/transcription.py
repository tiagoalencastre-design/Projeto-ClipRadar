"""
Transcrição do áudio do VOD, com timestamps por segmento E por palavra.

Usa faster-whisper. Suporta idioma FIXO (ex: "en", "pt") ou idioma
UNIVERSAL/automático (None) — nesse caso, detecta o idioma amostrando 3
pontos diferentes do vídeo (início, meio, fim).
"""
from __future__ import annotations

import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from faster_whisper import WhisperModel


@dataclass
class TranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str
    words: list[dict] = None  # cada item: {"start": float, "end": float, "word": str}

    def __post_init__(self):
        if self.words is None:
            self.words = []


def _get_duration(video_path: str) -> float | None:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def _extract_audio_sample(video_path: str, start_seconds: float, duration_seconds: float, output_path: str) -> bool:
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_seconds),
        "-i", video_path,
        "-t", str(duration_seconds),
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def detect_dominant_language(model: WhisperModel, video_path: str, sample_seconds: float = 20.0, sample_count: int = 3) -> str | None:
    duration = _get_duration(video_path)
    if duration is None:
        return None

    if duration <= sample_seconds:
        sample_starts = [0.0]
    else:
        margin = duration * 0.1
        usable_range = max(duration - 2 * margin - sample_seconds, 0)
        sample_starts = [
            margin + (usable_range * i / max(sample_count - 1, 1))
            for i in range(sample_count)
        ]

    votes = Counter()
    with tempfile.TemporaryDirectory() as tmp_dir:
        for i, start in enumerate(sample_starts):
            sample_path = str(Path(tmp_dir) / f"lang_sample_{i}.wav")
            if not _extract_audio_sample(video_path, start, sample_seconds, sample_path):
                continue
            try:
                _, info = model.transcribe(sample_path, language=None, vad_filter=True)
                if info.language:
                    votes[info.language] += (info.language_probability or 0.5)
            except Exception:
                continue

    if not votes:
        return None
    return votes.most_common(1)[0][0]


def transcribe(video_path: str, model_size: str = "base", language: str | None = "pt") -> list[TranscriptSegment]:
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    resolved_language = language
    if language is None:
        resolved_language = detect_dominant_language(model, video_path)

    segments, _info = model.transcribe(
        video_path, language=resolved_language, vad_filter=True, word_timestamps=True
    )

    result = []
    for seg in segments:
        words = [
            {"start": w.start, "end": w.end, "word": w.word.strip()}
            for w in (seg.words or [])
            if w.word.strip()
        ]
        result.append(TranscriptSegment(
            start_seconds=seg.start,
            end_seconds=seg.end,
            text=seg.text.strip(),
            words=words,
        ))
    return result


def text_around(transcript: list[TranscriptSegment], timestamp: float, window_seconds: float = 15.0) -> str:
    relevant = [
        seg.text for seg in transcript
        if abs(seg.start_seconds - timestamp) <= window_seconds
    ]
    return " ".join(relevant)