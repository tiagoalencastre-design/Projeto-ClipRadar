"""
Execução do FFmpeg e sondagem de vídeo.

Concentra o que fala com o binário: rodar comando, ler duração e fps, e
os parâmetros de saída padronizados.

VIDEO_OUTPUT_ARGS existe porque cada codificação solta divergia (fps e
base de tempo herdados da origem). Ao concatenar pedaços diferentes, os
timestamps saíam fora de ordem e o arquivo não abria no Windows.
Use SEMPRE estes argumentos; nunca monte parâmetros de saída à mão.
"""
from __future__ import annotations

import subprocess


class MontageError(Exception):
    """Falha ao cortar, renderizar ou juntar vídeo."""


# Parâmetros de saída usados em TODA codificação de vídeo do projeto.
#
# POR QUE ISTO EXISTE: sem padronizar, cada trecho saía com fps e base de
# tempo herdados do vídeo de origem. Ao juntar pedaços diferentes com
# "concat -c copy", os timestamps ficavam fora de ordem e o arquivo final
# não abria no Windows ("unsupported encoding settings", 0x80004005).
#
# - pix_fmt yuv420p : o único formato que todo player e toda rede social
#                     aceitam. Sem isso, o x264 pode sair em yuv444p e o
#                     arquivo não abre em player nenhum.
# - r 30            : fps fixo, pra que os pedaços possam ser concatenados.
# - video_track_timescale : mesma base de tempo em todos os pedaços.
# - ar/ac           : áudio uniforme (48 kHz estéreo), mesma razão.
# - faststart       : move o índice pro começo do arquivo, o que faz o
#                     vídeo começar a tocar antes de baixar inteiro.
VIDEO_OUTPUT_ARGS = [
    "-c:v", "libx264",
    "-preset", "veryfast",
    "-crf", "23",
    "-pix_fmt", "yuv420p",
    "-r", "30",
    "-video_track_timescale", "15360",
    "-c:a", "aac",
    "-b:a", "192k",
    "-ar", "48000",
    "-ac", "2",
    "-movflags", "+faststart",
]


def _run_ffmpeg(cmd: list[str], step_description: str) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise MontageError(
            f"Falha ao {step_description}. Detalhe técnico (últimas linhas):\n"
            f"{result.stderr.strip()[-800:]}"
        )


def get_duration(video_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise MontageError(f"Não consegui ler a duração de {video_path}.")
    try:
        return float(result.stdout.strip())
    except ValueError:
        raise MontageError(f"Resultado inesperado ao medir a duração de {video_path}.")


def get_fps(video_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        num, den = result.stdout.strip().split("/")
        fps = float(num) / float(den)
        return fps if fps > 0 else 30.0
    except Exception:
        return 30.0
