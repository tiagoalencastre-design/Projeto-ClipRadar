"""
Entrega autenticada de arquivos de mídia.

O PROBLEMA QUE ISTO CORRIGE:

    app.mount("/files/clips", StaticFiles(directory=CLIPS_DIR))
    app.mount("/files/vods",  StaticFiles(directory=VODS_DIR))

O StaticFiles não passa por autenticação nenhuma. As APIs exigiam login para
DESCOBRIR o caminho de um arquivo, mas quem soubesse o caminho baixava sem
sessão — e o caminho é previsível se a storage_key vazar (ela aparece na URL
de todo clipe que o usuário compartilha ou tem aberto no navegador).

Aqui cada download passa por três checagens:
  1. sessão válida (dependência get_current_user);
  2. caminho resolvido dentro da pasta do PRÓPRIO usuário (bloqueia "..");
  3. arquivo existe.

SOBRE RANGE REQUESTS:
    O FileResponse do Starlette 0.38 NÃO trata o cabeçalho Range. Sem isso,
    o navegador não consegue arrastar a barra do vídeo e alguns nem iniciam
    a reprodução. Por isso a resposta 206 é montada aqui.
"""
from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from typing import Iterator

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

CHUNK_SIZE = 1024 * 256   # 256 KB por leitura

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def resolve_user_file(base_dir: Path, storage_key: str, relative_path: str) -> Path:
    """
    Caminho absoluto do arquivo, garantindo que ele pertence ao usuário.

    ATENÇÃO AO FORMATO: a URL é /files/clips/<storage_key>/<arquivo>, ou
    seja, relative_path JÁ COMEÇA com a storage_key. Por isso resolvemos a
    partir de base_dir, não de base_dir/storage_key — senão o segmento
    apareceria duplicado e nenhum arquivo seria encontrado.

    A validação de dono é feita depois, comparando caminhos JÁ RESOLVIDOS:
    é o que impede "../outro_usuario/clip.mp4" de escapar da pasta.
    """
    user_dir = (base_dir / storage_key).resolve()
    candidate = (base_dir / relative_path).resolve()

    try:
        candidate.relative_to(user_dir)
    except ValueError:
        # Não dizemos "acesso negado": isso confirmaria que o arquivo existe.
        raise HTTPException(404, "Arquivo não encontrado.")

    if not candidate.is_file():
        raise HTTPException(404, "Arquivo não encontrado.")
    return candidate


def _read_range(path: Path, start: int, end: int) -> Iterator[bytes]:
    remaining = end - start + 1
    with open(path, "rb") as handle:
        handle.seek(start)
        while remaining > 0:
            chunk = handle.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def serve_file(path: Path, request: Request):
    """
    Entrega o arquivo, respeitando Range quando o navegador pedir.

    Sem Range devolve 200 com o arquivo inteiro; com Range devolve 206 e só
    a fatia pedida, que é como o player consegue pular para um ponto do
    vídeo sem baixar tudo.
    """
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    file_size = path.stat().st_size
    range_header = request.headers.get("range")

    if not range_header:
        return FileResponse(
            path, media_type=media_type,
            headers={"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"},
        )

    match = _RANGE_RE.fullmatch(range_header.strip())
    if not match:
        raise HTTPException(416, "Range inválido.")

    raw_start, raw_end = match.groups()
    if raw_start:
        start = int(raw_start)
        end = int(raw_end) if raw_end else file_size - 1
    else:
        # "bytes=-500" significa os ÚLTIMOS 500 bytes.
        if not raw_end:
            raise HTTPException(416, "Range inválido.")
        start = max(file_size - int(raw_end), 0)
        end = file_size - 1

    end = min(end, file_size - 1)
    if start > end or start >= file_size:
        return StreamingResponse(
            iter(()), status_code=416,
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    return StreamingResponse(
        _read_range(path, start, end),
        status_code=206,
        media_type=media_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(end - start + 1),
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, max-age=3600",
        },
    )
