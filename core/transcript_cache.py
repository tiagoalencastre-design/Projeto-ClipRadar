"""
Cache de transcrição.

O PROBLEMA: reanalisar o mesmo VOD roda o Whisper de novo. Numa live de uma
hora, com o modelo `medium` na CPU, isso são muitos minutos gastos para
produzir exatamente o mesmo texto.

QUANDO ISSO ACONTECE NA PRÁTICA:
  - você ajusta um peso do scoring e quer comparar o resultado;
  - o benchmark roda o pipeline em 10 VODs, e depois roda de novo;
  - o usuário processa o mesmo vídeo em "clipes separados" e em "montagem".

A CHAVE É O CONTEÚDO, NÃO O CAMINHO. Renomear o arquivo não invalida o
cache; trocar o conteúdo invalida. Isso importa porque o mesmo VOD pode ser
enviado por dois usuários com nomes diferentes.

O modelo e o idioma entram na chave: transcrição feita com `base` não pode
ser reaproveitada quando a configuração pede `medium`.

SOBRE O HASH DE ARQUIVOS GRANDES: ler um VOD de 3 GB inteiro para calcular
SHA-256 levaria quase tanto quanto transcrever. Lemos amostras do começo,
meio e fim, mais o tamanho exato — o suficiente para distinguir vídeos
diferentes sem pagar a leitura completa.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from core.observability import log_event
from core.transcription import TranscriptSegment

# Quanto ler de cada trecho ao calcular a impressão digital.
SAMPLE_BYTES = 1024 * 1024   # 1 MB
CACHE_VERSION = 1            # muda se o formato do arquivo mudar


def fingerprint(video_path: str | Path) -> str | None:
    """
    Impressão digital do conteúdo do vídeo.

    Amostra três trechos (início, meio, fim) e inclui o tamanho exato. Dois
    vídeos diferentes teriam que coincidir nos três trechos E no byte exato
    de tamanho para colidir — o que não acontece na prática.

    Devolve None se o arquivo não puder ser lido: sem impressão digital,
    o cache é simplesmente ignorado e o Whisper roda normalmente.
    """
    path = Path(video_path)
    try:
        size = path.stat().st_size
    except OSError:
        return None

    digest = hashlib.sha256()
    digest.update(str(size).encode())

    try:
        with open(path, "rb") as handle:
            for offset in (0, max(size // 2 - SAMPLE_BYTES // 2, 0),
                           max(size - SAMPLE_BYTES, 0)):
                handle.seek(offset)
                digest.update(handle.read(SAMPLE_BYTES))
    except OSError:
        return None

    return digest.hexdigest()


def cache_path(cache_dir: Path, video_path: str | Path,
               model_size: str, language: str | None) -> Path | None:
    """Onde a transcrição deste vídeo, com esta configuração, fica guardada."""
    digital = fingerprint(video_path)
    if digital is None:
        return None
    key = f"{digital[:16]}_{model_size}_{language or 'auto'}_v{CACHE_VERSION}"
    return Path(cache_dir) / "transcripts" / f"{key}.json"


def load(path: Path | None) -> list[TranscriptSegment] | None:
    """
    Lê uma transcrição guardada. None se não existir ou estiver corrompida.

    Arquivo corrompido é tratado como ausência: transcrever de novo custa
    tempo, mas devolver texto quebrado corromperia todos os clipes.
    """
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        segments = [
            TranscriptSegment(
                start_seconds=float(item["start_seconds"]),
                end_seconds=float(item["end_seconds"]),
                text=item["text"],
                words=item.get("words") or [],
            )
            for item in data["segments"]
        ]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, OSError):
        return None

    if not segments:
        return None
    log_event(stage="transcricao_reaproveitada", segments=len(segments))
    return segments


def save(path: Path | None, segments: list[TranscriptSegment]) -> bool:
    """
    Guarda a transcrição. Falha aqui nunca interrompe o processamento — o
    texto já está em memória e o clipe sai do mesmo jeito.
    """
    if path is None or not segments:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"version": CACHE_VERSION,
                 "segments": [asdict(s) for s in segments]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return True
    except OSError as e:
        log_event(stage="cache_de_transcricao", status="error", error=str(e))
        return False
