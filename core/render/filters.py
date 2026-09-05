"""
Filtros de vídeo do FFmpeg.

Funções PURAS: recebem parâmetros, devolvem string de filtro. Nenhuma
toca em disco ou executa processo — por isso são fáceis de testar sem
renderizar nada.

ARMADILHAS JÁ PAGAS (não repita):
  - vírgula dentro de expressão de filtro precisa de "\\,"
  - caminho de arquivo com ":" (drive do Windows) precisa de "\\:",
    senão o FFmpeg lê só a letra do drive
  - scale com altura "-2" (não "-1"): o H.264 exige altura par
"""
from __future__ import annotations

from pathlib import Path

VERTICAL_FILTER = "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920"
HORIZONTAL_FILTER = "scale=1920:1080"
VERTICAL_RES = (1080, 1920)
HORIZONTAL_RES = (1920, 1080)


def _zoom_filter(duration_seconds: float, play_res: tuple[int, int], fps: float, zoom_amount: float = 0.06) -> str:
    """Zoom CONTÍNUO (legado) — câmera se aproximando devagar o clip inteiro.
    Mantido pra compatibilidade com dynamic_zoom=True, mas o preset "impact"
    usa _build_punch_in_zoom_filter em vez deste, que é mais parecido com
    decisão de editor de verdade (zoom só no momento que importa)."""
    total_frames = max(int(duration_seconds * fps), 1)
    increment = zoom_amount / total_frames
    width, height = play_res
    return (
        f"zoompan=z='min(zoom+{increment:.8f},{1 + zoom_amount})':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d=1:s={width}x{height}:fps={fps:.3f}"
    )


def _build_punch_in_zoom_filter(
    zoom_events: list[dict],
    clip_start: float,
    fps: float,
    play_res: tuple[int, int],
    zoom_amount: float = 0.15,
    ramp_seconds: float = 0.25,
) -> str | None:
    """
    EXPERIMENTAL (P1): zoom curto ("punch-in") só nos instantes marcados no
    Edit Plan — diferente do zoom contínuo antigo (_zoom_filter), que ficava
    "grudado" no clip inteiro. Fora das janelas marcadas, o vídeo fica sem
    zoom nenhum (zoom = 1.0).

    `clip_start` é o timestamp ABSOLUTO de onde o clip cortado começa (pra
    converter os eventos do plano, que também são absolutos, em tempo
    relativo ao arquivo já cortado, que sempre começa em t=0).

    Nota honesta: a suavidade da entrada/saída do zoom é uma aproximação
    (rampa linear com base em on/fps) — não testei renderização real aqui,
    então recomendo validar visualmente antes de confiar 100% nesse efeito.
    """
    if not zoom_events:
        return None

    width, height = play_res
    conditions = []
    for ev in zoom_events:
        rel_start = max(ev["start"] - clip_start, 0.0)
        rel_end = max(ev["end"] - clip_start, rel_start + 0.3)
        ramp = min(ramp_seconds, (rel_end - rel_start) / 2)

        t_expr = f"(on/{fps:.3f})"
        conditions.append(
            f"if(between({t_expr},{rel_start:.3f},{rel_start + ramp:.3f}),"
            f"1+{zoom_amount}*(({t_expr}-{rel_start:.3f})/{max(ramp, 0.01):.3f}),"
            f"if(between({t_expr},{rel_start + ramp:.3f},{rel_end - ramp:.3f}),{1 + zoom_amount:.4f},"
            f"if(between({t_expr},{rel_end - ramp:.3f},{rel_end:.3f}),"
            f"1+{zoom_amount}*(1-(({t_expr}-({rel_end - ramp:.3f}))/{max(ramp, 0.01):.3f})),1)))"
        )

    zoom_expr = conditions[0] if len(conditions) == 1 else "max(" + ",".join(conditions) + ")"

    return (
        f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d=1:s={width}x{height}:fps={fps:.3f}"
    )


def _find_keep_intervals(
    words: list[dict], start: float, end: float, max_gap: float = 3.0, padding: float = 0.4, min_segment_length: float = 1.0
) -> list[tuple[float, float]]:
    """
    Acha pausas de silêncio REALMENTE longas (sem nenhuma palavra falada)
    DENTRO do trecho, e retorna os intervalos que devem ser MANTIDOS.

    Sendo conservador de propósito (P0.4): o limiar padrão (max_gap=3.0s) só
    corta silêncios bem longos — evita remover gameplay silenciosa mas
    importante (ex: uma sequência de tensão sem ninguém falando). A margem
    (padding) também é generosa, pra nunca cortar em cima do começo/fim de
    uma fala. Se o resultado ficaria muito picado (muitos pedacinhos) ou sem
    nada aproveitável, a função prefere NÃO cortar nada a entregar um clip
    confuso.
    """
    relevant = sorted([w for w in words if w["end"] > start and w["start"] < end], key=lambda w: w["start"])
    if not relevant:
        return [(start, end)]

    intervals = []
    cur_start = start
    prev_end = start
    for w in relevant:
        gap = w["start"] - prev_end
        if gap > max_gap:
            intervals.append((cur_start, min(prev_end + padding, end)))
            cur_start = max(w["start"] - padding, prev_end)
        prev_end = max(prev_end, w["end"])

    # trecho final: só encurta se sobrar silêncio realmente longo até o fim
    # do momento; caso contrário, estende até "end" de verdade — sem isso,
    # a cauda do clip era cortada por engano mesmo sem nenhum motivo real
    # (bug corrigido no P0.4)
    final_gap = end - prev_end
    final_end = min(prev_end + padding, end) if final_gap > max_gap else end
    intervals.append((cur_start, final_end))

    # descarta fragmentos curtos demais (ficariam confusos, corte muito brusco)
    kept = [(s, e) for s, e in intervals if e - s >= min_segment_length]

    # válvula de segurança: se o corte deixaria o clip bem fatiado (muitos
    # pedaços) ou não sobrou nada aproveitável, é mais seguro devolver o
    # trecho original inteiro do que arriscar um resultado picado/confuso
    if not kept or len(kept) > 4:
        return [(start, end)]

    return kept


def _build_facecam_stack_filter(bbox: tuple[float, float, float, float], play_res: tuple[int, int]) -> str:
    """
    Monta o filtro composto do layout "gameplay + facecam": gameplay em cima
    (sem cortar nada, só encaixado — protege o HUD), webcam do criador
    recortada embaixo. Retorna uma string de filter_complex terminando no
    label [__stacked].
    """
    width, height = play_res
    bg_height_px = int(height * 0.62)
    fc_height_px = height - bg_height_px

    x_frac, y_frac, w_frac, h_frac = bbox
    cx_frac = x_frac + w_frac / 2
    cy_frac = y_frac + h_frac / 2

    # expande a caixa do rosto pra um enquadramento tipo "webcam" (não só o
    # rosto colado), com folga generosa em volta
    crop_w_frac = min(w_frac * 2.6, 1.0)
    crop_h_frac = min(h_frac * 2.6, 1.0)
    crop_x_frac = max(0.0, min(cx_frac - crop_w_frac / 2, 1.0 - crop_w_frac))
    crop_y_frac = max(0.0, min(cy_frac - crop_h_frac / 2, 1.0 - crop_h_frac))

    return (
        f"[0:v]split=2[__bg][__fc];"
        # gameplay: SEM cortar (scale+pad, não crop) — preserva HUD/cantos da tela
        f"[__bg]scale={width}:{bg_height_px}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{bg_height_px}:(ow-iw)/2:(oh-ih)/2:color=black[__bgout];"
        # facecam: recorta só a região do rosto (com folga), esse sim é pra cortar
        f"[__fc]crop=iw*{crop_w_frac:.4f}:ih*{crop_h_frac:.4f}:iw*{crop_x_frac:.4f}:ih*{crop_y_frac:.4f},"
        f"scale={width}:{fc_height_px}[__fcout];"
        f"[__bgout][__fcout]vstack=inputs=2[__stacked]"
    )


# Raiz do projeto. Este arquivo está em core/render/, então são TRÊS níveis
# acima — não dois. Ao mover o módulo de core/ para core/render/, o caminho
# passou a apontar para core/web/assets/ e a marca d'água sumiu.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
WATERMARK_PATH = _PROJECT_ROOT / "web" / "assets" / "watermark.png"


def build_watermark_filter(
    play_res: tuple[int, int], opacity: float = 0.75, margin: int = 34,
    image_path: Path | str | None = None,
) -> str | None:
    """
    Marca d'água do plano grátis, no canto inferior direito.

    DISCRETA DE PROPÓSITO. Marca agressiva faz a pessoa não postar o clipe —
    e aí ela não divulga o produto nem vira cliente. O objetivo é ser
    reconhecível, não atrapalhar.

    Devolve None se o arquivo da marca não existir: é melhor entregar o
    clipe sem marca do que falhar a renderização inteira por causa dela.
    """
    source = Path(image_path) if image_path else WATERMARK_PATH
    if not source.exists():
        return None

    # ESCAPE OBRIGATÓRIO NO WINDOWS.
    #
    # Dentro de um filter_complex, ":" separa argumentos de filtro. Um
    # caminho como "C:/Users/.../watermark.png" faz o FFmpeg ler apenas "C"
    # como nome do arquivo e tratar o resto como opção:
    #     Failed to avformat_open_input 'C'
    #
    # Resultado prático: a marca d'água NÃO renderizava em nenhuma máquina
    # Windows — ou seja, o plano grátis inteiro quebrava. Escapar a letra
    # do drive resolve. No Linux/macOS não há ":" e nada muda.
    escaped = source.as_posix().replace(":", "\\:")

    width = max(int(play_res[0] * 0.30), 120)   # ~30% da largura do vídeo
    return (
        f"movie='{escaped}'[__wm];"
        f"[__wm]scale={width}:-1,format=rgba,"
        f"colorchannelmixer=aa={opacity}[__wms];"
        f"[__wms]null[__wmf]"
    )


def append_watermark(
    filter_complex: str, play_res: tuple[int, int],
    image_path: Path | str | None = None, opacity: float = 0.75,
) -> str:
    """
    Encaixa a marca no fim de um filter_complex que termina em [__stacked].

    image_path aponta pra logo do canal (Brand Kit, plano Studio). Sem ela,
    usa a marca do ClipRadar.

    Feito como etapa separada pra funcionar com QUALQUER layout — corte
    central, facecam empilhado ou fundo borrado.
    """
    watermark = build_watermark_filter(play_res, opacity=opacity, image_path=image_path)
    if not watermark:
        return filter_complex

    base = filter_complex.replace("[__stacked]", "[__prewm]")
    return (
        f"{base};{watermark};"
        f"[__prewm][__wmf]overlay=W-w-34:H-h-34[__stacked]"
    )


def _build_blur_background_filter(play_res: tuple[int, int], blur_strength: int = 22) -> str:
    """
    Layout "blur_background": vídeo inteiro no centro, fundo borrado.

    POR QUE ESTE LAYOUT EXISTE: o corte central 9:16 de um gameplay 16:9
    joga fora quase 70% da largura da tela. Em jogo, é justamente nas
    laterais que ficam minimapa, kill feed, vida e munição — o corte
    central apaga tudo isso.

    Aqui o frame inteiro é preservado: ele entra escalado pela largura, e o
    espaço que sobraria em cima e embaixo é preenchido com uma cópia do
    próprio vídeo, ampliada até cobrir a tela e desfocada. Fica muito melhor
    que tarja preta e não custa nada em qualidade do conteúdo principal.

    Retorna um filter_complex terminando em [__stacked], que é o rótulo que
    o resto da montagem (zoom, legenda) espera.
    """
    width, height = play_res
    return (
        f"[0:v]split=2[__bg][__fg];"
        # FUNDO: amplia até cobrir a tela inteira, corta o excedente e borra.
        # force_original_aspect_ratio=increase garante que não sobre buraco.
        f"[__bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},boxblur={blur_strength}:2,"
        # escurece um pouco pro fundo não competir com o conteúdo principal
        f"eq=brightness=-0.06[__bgout];"
        # FRENTE: o vídeo inteiro, escalado pela largura. -2 mantém a
        # proporção e garante altura par (exigência do codec H.264).
        f"[__fg]scale={width}:-2[__fgout];"
        f"[__bgout][__fgout]overlay=(W-w)/2:(H-h)/2[__stacked]"
    )
