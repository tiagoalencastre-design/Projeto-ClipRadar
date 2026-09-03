"""
Monta um clip final combinando os melhores momentos do MESMO VOD numa única
edição: reframe vertical (9:16, padrão, com opção de seguir rosto/webcam) ou
horizontal, transição suave adaptativa, legenda animada palavra por palavra,
corte de silêncio interno (opcional), e normalização de volume.

P1 — Edit Plan: pros MELHORES candidatos, opcionalmente gera um plano
editorial via IA (core/edit_plan.py) com tipo de clip, hook/payoff/saída,
palavras pra destacar, se corte de silêncio é seguro, e onde aplicar zoom
"punch-in" curto (em vez de zoom contínuo no clip inteiro). Se a IA estiver
desligada ou falhar, tudo continua funcionando sem o plano.

Presets de saída:
- "clean": discreto, sem zoom, sem destaque extra de palavra
- "impact": zoom "punch-in" nos eventos do plano (se houver) + destaque de
  palavras-chave na legenda

Features experimentais (desligadas por padrão, ligue com cuidado):
- dynamic_zoom: zoom contínuo tipo "câmera se aproximando" (legado, use o
  preset "impact" + Edit Plan pra zoom mais inteligente em vez deste)
- trim_dead_air: remove pausas/silêncio longos DENTRO de um mesmo momento
  (agora também respeita o silence_cut_safe do Edit Plan, quando disponível)
- auto_face_crop: em vez de cortar sempre no centro (vertical), tenta manter
  um rosto/webcam detectado dentro do enquadramento
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.thumbnail import extract_thumbnail, derive_thumbnail_text, get_thumbnail_text
from core.subtitles import build_ass_karaoke, STYLE_PRESETS, DEFAULT_STYLE
from core.face_crop import detect_face_offset_fraction, build_face_aware_crop_filter, detect_face_bbox_fraction
from core.pipeline import load_config

VERTICAL_FILTER = "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920"
HORIZONTAL_FILTER = "scale=1920:1080"

VERTICAL_RES = (1080, 1920)
HORIZONTAL_RES = (1920, 1080)

SUBTITLE_STYLES = STYLE_PRESETS
DEFAULT_SUBTITLE_STYLE = DEFAULT_STYLE

# Presets de saída — "o quanto o Edit Plan pode se expressar" na renderização
EDIT_PRESETS = {
    "clean": {
        "zoom_enabled": False,
        "highlight_words_enabled": False,
    },
    "impact": {
        "zoom_enabled": True,
        "highlight_words_enabled": True,
    },
    "streamer": {
        # Mesma base técnica do "impact" (zoom pontual + destaque de palavra),
        # mas pensado pra quem grava com facecam: combina bem com o layout
        # "gameplay + facecam" e um estilo de legenda mais expressivo por
        # padrão. Nota honesta: a diferença de hoje é modesta — não há
        # lógica exclusiva do "streamer" além disso ainda.
        "zoom_enabled": True,
        "highlight_words_enabled": True,
        "default_subtitle_style": "bold_yellow",
    },
}
DEFAULT_PRESET = "clean"

# Opções de layout do recorte vertical (tela de revisão) — "gameplay_full" é
# o corte central simples (comportamento antigo), "facecam_focus" segue o
# rosto detectado (comportamento antigo do auto_face_crop), e
# "gameplay_facecam" é NOVO: empilha gameplay em cima e a webcam do criador
# embaixo, só quando um rosto é realmente detectado (senão cai pra gameplay_full).
LAYOUT_OPTIONS = {"gameplay_full", "gameplay_facecam", "facecam_focus"}
DEFAULT_LAYOUT = "gameplay_full"

PLATFORM_DURATION_PRESETS = {
    "tiktok": 34.0,
    "reels": 90.0,
    "shorts": 60.0,
    "sem_preferencia": None,
}
DEFAULT_PLATFORM = "sem_preferencia"


class MontageError(Exception):
    pass


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


def select_moments_for_montage(all_moments: list[dict], score_threshold: float, max_total_duration: float) -> list[dict]:
    candidates = [m for m in all_moments if m["score"] >= score_threshold]
    candidates.sort(key=lambda m: m["score"], reverse=True)

    selected = []
    total_duration = 0.0
    for m in candidates:
        duration = m["end_seconds"] - m["context_start_seconds"]
        if total_duration + duration > max_total_duration and selected:
            continue
        selected.append(m)
        total_duration += duration

    selected.sort(key=lambda m: m["start_seconds"])
    return selected


def _selection_config() -> dict:
    """Lê clip_selection do settings.yaml. Se faltar, usa os padrões — assim
    um settings.yaml antigo continua funcionando."""
    try:
        cfg = load_config().get("clip_selection", {}) or {}
    except Exception:
        cfg = {}
    # A seleção editorial mora em core/discovery.py (seção "selection" do
    # settings.yaml). Aqui só resta o teto de quantidade da renderização.
    selection = {}
    try:
        selection = load_config().get("selection", {}) or {}
    except Exception:
        pass
    return {
        "max_moments": int(selection.get("max_final_clips", cfg.get("max_clips", 20))),
        "min_moments": int(cfg.get("min_clips", 1)),
    }


def select_moments_automatically(
    all_moments: list[dict],
    min_moments: int = 1,
    max_moments: int = 20,
    score_floor: float | None = None,
    score_gap: float | None = None,
    max_total_duration: float | None = None,
    diversity_weight: float | None = None,
) -> list[dict]:
    """
    CAMADA DE COMPATIBILIDADE — não faz mais seleção editorial.

    A partir da V2, quem escolhe os clipes é core/discovery.py, ANTES do
    analysis.json ser salvo. Os momentos que chegam aqui já passaram por
    avaliação editorial, deduplicação e diversidade.

    Refazer a seleção aqui seria um segundo ranking concorrente — foi
    exatamente o problema que a integração da V2 veio eliminar. Por isso
    esta função agora só:

      - respeita o teto de quantidade pedido pela chamada;
      - respeita o teto de duração somada (usado na montagem única, pra
        caber no limite da plataforma);
      - devolve em ordem cronológica.

    Os parâmetros score_floor, score_gap e diversity_weight continuam na
    assinatura para não quebrar chamadas existentes, mas são IGNORADOS.
    Serão removidos quando nenhuma chamada antiga depender deles.
    """
    if not all_moments:
        return []

    # Já vêm ordenados por nota do discovery; reordenamos só por garantia.
    ordered = sorted(all_moments, key=lambda m: m.get("score", 0), reverse=True)

    selected = []
    total_duration = 0.0
    for m in ordered:
        if len(selected) >= max_moments:
            break
        duration = m["end_seconds"] - m["context_start_seconds"]
        if (max_total_duration is not None
                and total_duration + duration > max_total_duration
                and selected):
            continue
        selected.append(m)
        total_duration += duration

    if len(selected) < min_moments:
        selected = ordered[:min_moments]

    selected.sort(key=lambda m: m["start_seconds"])
    return selected


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


def _cut_single_interval(
    video_path: str,
    interval_start: float,
    interval_end: float,
    orientation: str,
    output_path: str,
    words: list[dict],
    burn_captions: bool,
    subtitle_style: str,
    srt_dir: str,
    clip_id: str,
    dynamic_zoom: bool,
    auto_face_crop: bool,
    edit_plan: dict | None = None,
    preset: str = DEFAULT_PRESET,
    layout: str | None = None,
) -> None:
    """
    layout: None mantém o comportamento antigo (usa auto_face_crop como
    antes) — só quando explicitamente "gameplay_facecam" ou "facecam_focus"
    é que o novo sistema de layout assume o controle. Isso preserva 100% de
    compatibilidade com quem já chama essa função sem o parâmetro novo.
    """
    duration = interval_end - interval_start
    play_res = VERTICAL_RES if orientation == "vertical" else HORIZONTAL_RES
    preset_config = EDIT_PRESETS.get(preset, EDIT_PRESETS[DEFAULT_PRESET])

    facecam_complex = None
    if orientation == "vertical" and layout == "gameplay_facecam":
        bbox = detect_face_bbox_fraction(video_path, interval_start, interval_end)
        if bbox:
            facecam_complex = _build_facecam_stack_filter(bbox, play_res)
        # se não achou rosto nenhum, cai pro corte simples abaixo (gameplay_full)
        # — nunca inventamos uma "webcam" que não existe

    vf_parts = None
    filter_chain = None
    if facecam_complex:
        filter_chain = [facecam_complex]
    else:
        use_face_follow = (layout == "facecam_focus") or (layout is None and auto_face_crop)
        if orientation == "vertical" and use_face_follow:
            face_x = detect_face_offset_fraction(video_path, interval_start, interval_end)
            vf_parts = [build_face_aware_crop_filter(face_x)]
        else:
            vf_parts = [VERTICAL_FILTER if orientation == "vertical" else HORIZONTAL_FILTER]

    # P1: zoom "punch-in" nos eventos do Edit Plan (só se o preset permitir e
    # houver plano com eventos) — tem prioridade sobre o zoom contínuo legado
    punch_in_filter = None
    if preset_config["zoom_enabled"] and edit_plan and edit_plan.get("zoom_events"):
        fps = get_fps(video_path)
        punch_in_filter = _build_punch_in_zoom_filter(edit_plan["zoom_events"], interval_start, fps, play_res)

    if not punch_in_filter and dynamic_zoom:
        fps = get_fps(video_path)
        punch_in_filter = _zoom_filter(duration, play_res, fps)

    subtitles_filter = None
    if burn_captions and words:
        highlight_words = None
        if preset_config["highlight_words_enabled"] and edit_plan:
            highlight_words = edit_plan.get("highlight_words")

        # o estilo de legenda escolhido pelo usuário sempre tem prioridade —
        # a recomendação do Edit Plan é só informativa (mostrada pro usuário
        # como sugestão), nunca troca o estilo por baixo dos panos sem avisar
        ass_content = build_ass_karaoke(
            words, interval_start, interval_end, style=subtitle_style, play_res=play_res,
            highlight_words=highlight_words,
        )
        if ass_content.strip():
            ass_path = str(Path(srt_dir) / f"{clip_id}.ass")
            Path(ass_path).write_text(ass_content, encoding="utf-8")
            escaped = ass_path.replace("\\", "/").replace(":", "\\:")
            subtitles_filter = f"subtitles='{escaped}'"

    if filter_chain is not None:
        stage_label = "__stacked"
        if punch_in_filter:
            filter_chain.append(f"[{stage_label}]{punch_in_filter}[__zoomed]")
            stage_label = "__zoomed"
        if subtitles_filter:
            filter_chain.append(f"[{stage_label}]{subtitles_filter}[__final]")
            stage_label = "__final"
        filter_complex_str = ";".join(filter_chain)
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(interval_start),
            "-i", video_path,
            "-t", str(duration),
            "-filter_complex", filter_complex_str,
            "-map", f"[{stage_label}]",
            "-map", "0:a",
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-c:a", "aac",
            output_path,
        ]
    else:
        if punch_in_filter:
            vf_parts.append(punch_in_filter)
        if subtitles_filter:
            vf_parts.append(subtitles_filter)
        vf = ",".join(vf_parts)
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(interval_start),
            "-i", video_path,
            "-t", str(duration),
            "-vf", vf,
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-c:a", "aac",
            output_path,
        ]
    _run_ffmpeg(cmd, f"cortar o trecho {clip_id}")


def _concat_hard_cut(piece_paths: list[str], output_path: str) -> None:
    list_file = str(Path(piece_paths[0]).parent / "concat_list.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for p in piece_paths:
            safe_path = Path(p).resolve().as_posix()
            f.write(f"file '{safe_path}'\n")

    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", output_path]
    _run_ffmpeg(cmd, "remontar o momento após remover silêncios")


def cut_reframe_and_caption(
    video_path: str,
    moment: dict,
    orientation: str,
    output_path: str,
    burn_captions: bool = True,
    srt_dir: str | None = None,
    subtitle_style: str = DEFAULT_SUBTITLE_STYLE,
    dynamic_zoom: bool = False,
    trim_dead_air: bool = False,
    auto_face_crop: bool = False,
    edit_plan: dict | None = None,
    preset: str = DEFAULT_PRESET,
    layout: str | None = None,
    start_override: float | None = None,
    end_override: float | None = None,
) -> None:
    start = start_override if start_override is not None else moment["context_start_seconds"]
    end = end_override if end_override is not None else moment["end_seconds"]
    words = moment.get("transcript_words", [])
    srt_dir = srt_dir or "."

    # P1: o Edit Plan pode vetar o corte de silêncio pra este momento
    # específico (silence_cut_safe=False), mesmo que trim_dead_air esteja
    # pedido globalmente — protege gameplay silenciosa importante (tensão,
    # mira, movimento sem fala) de ser cortada às cegas.
    effective_trim_dead_air = trim_dead_air
    if edit_plan is not None:
        effective_trim_dead_air = trim_dead_air and bool(edit_plan.get("silence_cut_safe", False))

    if effective_trim_dead_air:
        intervals = _find_keep_intervals(words, start, end)
    else:
        intervals = [(start, end)]

    if len(intervals) == 1:
        _cut_single_interval(
            video_path, intervals[0][0], intervals[0][1], orientation, output_path,
            words, burn_captions, subtitle_style, srt_dir, moment["clip_id"],
            dynamic_zoom, auto_face_crop, edit_plan=edit_plan, preset=preset, layout=layout,
        )
        return

    with tempfile.TemporaryDirectory(dir=srt_dir) as tmp_dir:
        piece_paths = []
        for i, (s, e) in enumerate(intervals):
            piece_path = str(Path(tmp_dir) / f"{moment['clip_id']}_part{i}.mp4")
            _cut_single_interval(
                video_path, s, e, orientation, piece_path,
                words, burn_captions, subtitle_style, tmp_dir, f"{moment['clip_id']}_p{i}",
                dynamic_zoom, auto_face_crop, edit_plan=edit_plan, preset=preset, layout=layout,
            )
            piece_paths.append(piece_path)
        _concat_hard_cut(piece_paths, output_path)


def build_montage_with_crossfade(
    segment_paths: list[str],
    moments: list[dict],
    min_transition: float,
    max_transition: float,
    output_path: str,
) -> None:
    if len(segment_paths) == 1:
        _run_ffmpeg(
            ["ffmpeg", "-y", "-i", segment_paths[0], "-c", "copy", output_path],
            "finalizar o vídeo com 1 único momento",
        )
        return

    durations = [get_duration(p) for p in segment_paths]

    inputs = []
    for p in segment_paths:
        inputs += ["-i", p]

    filter_parts = []
    prev_v, prev_a = "0:v", "0:a"
    cumulative = durations[0]

    for i in range(1, len(segment_paths)):
        emotion_a = moments[i - 1]["breakdown"]["emotional_reaction"]
        emotion_b = moments[i]["breakdown"]["emotional_reaction"]
        avg_intensity = (emotion_a + emotion_b) / 2

        transition_duration = max_transition - (max_transition - min_transition) * (avg_intensity / 100)
        transition_duration = round(max(min_transition, min(max_transition, transition_duration)), 2)

        offset = max(cumulative - transition_duration, 0)
        v_label, a_label = f"v{i}", f"a{i}"
        filter_parts.append(
            f"[{prev_v}][{i}:v]xfade=transition=fade:duration={transition_duration}:offset={offset}[{v_label}]"
        )
        filter_parts.append(
            f"[{prev_a}][{i}:a]acrossfade=d={transition_duration}[{a_label}]"
        )
        prev_v, prev_a = v_label, a_label
        cumulative += durations[i] - transition_duration

    filter_complex = ";".join(filter_parts)

    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filter_complex,
        "-map", f"[{prev_v}]",
        "-map", f"[{prev_a}]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        output_path,
    ]
    _run_ffmpeg(cmd, "juntar os momentos na montagem final")


def _attach_edit_plans(top_moments: list[dict], edit_plan_config: dict | None) -> None:
    """
    P1: gera o plano editorial (core/edit_plan.py) SÓ pros momentos já
    selecionados como "melhores" — nunca pro VOD inteiro. Anexa o resultado
    em cada moment como "_edit_plan" (chave só em memória, nunca é escrita de
    volta no analysis_*.json — preserva compatibilidade com análises antigas).

    Se edit_plan_config vier desligado/sem chave, ou qualquer chamada falhar,
    cada moment simplesmente fica com _edit_plan=None — o resto do pipeline
    continua funcionando normalmente, sem quebrar.
    """
    enabled = bool(edit_plan_config and edit_plan_config.get("enabled") and edit_plan_config.get("api_key"))
    if not enabled:
        for m in top_moments:
            m["_edit_plan"] = None
        return

    from core.edit_plan import generate_edit_plan

    api_key = edit_plan_config["api_key"]
    model = edit_plan_config.get("model", "gpt-4o-mini")
    for m in top_moments:
        m["_edit_plan"] = generate_edit_plan(m, api_key, model)


def _persist_edit_plans(analysis_path: str, top_moments: list[dict]) -> None:
    """
    Salva o Edit Plan gerado de volta no arquivo de análise (campo novo
    "edit_plan", sem underscore) — sem isso, reabrir a análise depois (pra
    re-renderizar 1 clip específico na tela de revisão) sempre veria o plano
    como vazio, já que ele só existia em memória. É uma adição puramente
    aditiva: análises antigas sem esse campo continuam funcionando normal
    (o código sempre usa .get(), nunca assume que a chave existe).
    """
    plans_by_clip_id = {m["clip_id"]: m.get("_edit_plan") for m in top_moments}
    if not any(plans_by_clip_id.values()):
        return  # nada de novo pra salvar (Edit Plan desligado ou tudo falhou)

    try:
        analysis_file = Path(analysis_path)
        analysis = json.loads(analysis_file.read_text(encoding="utf-8"))
        for moment in analysis["moments"]:
            plan = plans_by_clip_id.get(moment["clip_id"])
            if plan is not None:
                moment["edit_plan"] = plan
        analysis_file.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass  # salvar o plano é só uma otimização — nunca deve derrubar a geração do clip


def run_montage(
    analysis_path: str,
    auto: bool = True,
    max_moments: int = 20,
    score_threshold: float = 65.0,
    max_duration: float = 90.0,
    platform: str | None = None,
    orientation: str = "vertical",
    min_transition: float = 0.15,
    max_transition: float = 0.8,
    burn_captions: bool = True,
    subtitle_style: str = DEFAULT_SUBTITLE_STYLE,
    dynamic_zoom: bool = False,
    trim_dead_air: bool = False,
    auto_face_crop: bool = False,
    ai_title_config: dict | None = None,
    edit_plan_config: dict | None = None,
    preset: str = DEFAULT_PRESET,
    output_dir: str = "data/clips",
) -> tuple[str | None, str | None, dict | None, float | None]:
    """
    Retorna (caminho_do_video, caminho_do_thumbnail, edit_plan_do_melhor_momento, duracao_segundos).
    O 3º item é só informativo (explicação pro usuário) — None se o Edit Plan
    não estiver habilitado ou tiver falhado.
    """
    analysis_file = Path(analysis_path)
    if not analysis_file.exists():
        raise MontageError(f"Não encontrei o arquivo de análise em {analysis_path}. Rode a análise do vídeo primeiro.")

    analysis = json.loads(analysis_file.read_text(encoding="utf-8"))
    video_path = analysis["video_path"]
    if not Path(video_path).exists():
        raise MontageError(f"O vídeo original ({video_path}) não foi encontrado. Ele foi movido ou apagado?")

    if auto:
        platform_cap = PLATFORM_DURATION_PRESETS.get(platform) if platform else None
        sel = _selection_config()
        top_moments = select_moments_automatically(
            analysis["moments"],
            max_moments=max_moments or sel["max_moments"],
            min_moments=sel["min_moments"],
            max_total_duration=platform_cap,
        )
    else:
        top_moments = select_moments_for_montage(analysis["moments"], score_threshold, max_duration)

    if not top_moments:
        return None, None, None, None

    _attach_edit_plans(top_moments, edit_plan_config)
    _persist_edit_plans(analysis_path, top_moments)

    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=output_dir_path) as tmp_dir:
        segment_paths: list = [None] * len(top_moments)

        def _process_moment(index, moment):
            tmp_path = Path(tmp_dir) / f"segment_{index + 1}.mp4"
            cut_reframe_and_caption(
                video_path, moment, orientation, str(tmp_path), burn_captions=burn_captions,
                srt_dir=tmp_dir, subtitle_style=subtitle_style,
                dynamic_zoom=dynamic_zoom, trim_dead_air=trim_dead_air, auto_face_crop=auto_face_crop,
                edit_plan=moment.get("_edit_plan"), preset=preset,
            )
            return index, str(tmp_path)

        max_workers = min(len(top_moments), os.cpu_count() or 4)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_process_moment, i, m) for i, m in enumerate(top_moments)]
            for future in concurrent.futures.as_completed(futures):
                index, path = future.result()
                segment_paths[index] = path

        montage_name = "montage_" + "_".join(m["clip_id"][-6:] for m in top_moments) + ".mp4"
        output_path = output_dir_path / montage_name

        build_montage_with_crossfade(segment_paths, top_moments, min_transition, max_transition, str(output_path))

        best_moment = max(top_moments, key=lambda m: m["score"])
        thumbnail_path = output_dir_path / (montage_name.replace(".mp4", ".jpg"))
        thumb_text = get_thumbnail_text(best_moment.get("transcript_excerpt", ""), ai_title_config)
        extract_thumbnail(video_path, best_moment["start_seconds"], str(thumbnail_path), text=thumb_text)

    # duração real do arquivo final (não dá pra só somar os momentos, porque
    # as transições com crossfade encavalam o fim de um com o começo do
    # próximo) — pega direto do arquivo já pronto, que é a fonte da verdade
    final_duration = get_duration(str(output_path))

    return str(output_path), str(thumbnail_path), best_moment.get("_edit_plan"), final_duration


def export_separate_clips(
    analysis_path: str,
    max_moments: int = 20,
    score_floor: float = 50.0,
    score_gap: float = 20.0,
    platform: str | None = None,
    orientation: str = "vertical",
    burn_captions: bool = True,
    subtitle_style: str = DEFAULT_SUBTITLE_STYLE,
    dynamic_zoom: bool = False,
    trim_dead_air: bool = False,
    auto_face_crop: bool = False,
    ai_title_config: dict | None = None,
    edit_plan_config: dict | None = None,
    preset: str = DEFAULT_PRESET,
    output_dir: str = "data/clips",
) -> list[dict]:
    """
    Modo "clipes separados" (inspirado no OpusClip/Vizard, e priorizado no
    P1): em vez de juntar os melhores momentos numa única montagem, exporta
    cada um como um clip independente — você escolhe qual postar. Cada clip
    já sai com Edit Plan (se habilitado), zoom "punch-in", legenda com
    destaque, thumbnail etc.

    Retorna uma lista de dicts: [{"clip_id", "score", "video_path",
    "thumbnail_path", "edit_plan"}, ...] ordenada da maior pra menor nota.
    "edit_plan" vem None se a IA de plano editorial estiver desligada ou
    tiver falhado pra aquele clip específico — nunca quebra o export.
    """
    analysis_file = Path(analysis_path)
    if not analysis_file.exists():
        raise MontageError(f"Não encontrei o arquivo de análise em {analysis_path}. Rode a análise do vídeo primeiro.")

    analysis = json.loads(analysis_file.read_text(encoding="utf-8"))
    video_path = analysis["video_path"]
    if not Path(video_path).exists():
        raise MontageError(f"O vídeo original ({video_path}) não foi encontrado. Ele foi movido ou apagado?")

    # aqui não faz sentido um teto de DURAÇÃO SOMADA (isso era só pro modo de
    # montagem única caber numa plataforma) — cada clip tem sua duração
    # própria, já limitada pelo min/max_duration_seconds do settings.yaml
    sel = _selection_config()
    top_moments = select_moments_automatically(
        analysis["moments"], max_moments=max_moments or sel["max_moments"],
        min_moments=sel["min_moments"],
    )
    if not top_moments:
        return []

    _attach_edit_plans(top_moments, edit_plan_config)
    _persist_edit_plans(analysis_path, top_moments)

    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    results: list[dict | None] = [None] * len(top_moments)

    def _process(index: int, moment: dict):
        clip_path = output_dir_path / f"{moment['clip_id']}.mp4"
        cut_reframe_and_caption(
            video_path, moment, orientation, str(clip_path),
            burn_captions=burn_captions, srt_dir=str(output_dir_path),
            subtitle_style=subtitle_style, dynamic_zoom=dynamic_zoom,
            trim_dead_air=trim_dead_air, auto_face_crop=auto_face_crop,
            edit_plan=moment.get("_edit_plan"), preset=preset,
        )
        thumb_path = output_dir_path / f"{moment['clip_id']}.jpg"
        thumb_text = get_thumbnail_text(moment.get("transcript_excerpt", ""), ai_title_config)
        extract_thumbnail(video_path, moment["start_seconds"], str(thumb_path), text=thumb_text)
        return index, {
            "clip_id": moment["clip_id"],
            "score": moment["score"],
            "duration_seconds": round(moment["end_seconds"] - moment["context_start_seconds"], 1),
            "video_path": str(clip_path),
            "thumbnail_path": str(thumb_path),
            "edit_plan": moment.get("_edit_plan"),
            # Sinais do Content Score — a interface usa pra explicar ao
            # usuário POR QUE este momento foi escolhido, sem custo de IA.
            "breakdown": moment.get("breakdown"),
        }

    max_workers = min(len(top_moments), os.cpu_count() or 4)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_process, i, m) for i, m in enumerate(top_moments)]
        for future in concurrent.futures.as_completed(futures):
            index, result = future.result()
            results[index] = result

    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def group_words_into_phrases(words: list[dict]) -> list[dict]:
    """
    Agrupa palavras com timestamp em frases (corta em pontuação final), pra
    tela de revisão mostrar a transcrição já "legível" e clicável — em vez
    de uma lista de palavras soltas. Se nunca aparecer pontuação (transcrição
    "crua"), cai num agrupamento por tamanho fixo (a cada ~8 palavras), pra
    nunca virar uma frase gigante única e inútil de clicar.

    Retorna: [{"text", "start", "end"}, ...]
    """
    if not words:
        return []

    groups: list[list[dict]] = []
    current: list[dict] = []
    for w in words:
        current.append(w)
        text = (w.get("word") or "").strip()
        if text.endswith((".", "!", "?")) or len(current) >= 8:
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    phrases = []
    for group in groups:
        if not group:
            continue
        text = " ".join((g.get("word") or "").strip() for g in group).strip()
        if not text:
            continue
        phrases.append({"text": text, "start": group[0]["start"], "end": group[-1]["end"]})
    return phrases


def get_candidates_for_review(analysis_path: str, max_candidates: int = 8) -> list[dict]:
    """
    Expõe os melhores momentos candidatos pra tela de revisão, SEM renderizar
    nada — só os dados já existentes na análise (score, transcrição por
    palavra já agrupada em frases, Edit Plan se já tiver sido persistido).

    Compatível com análises antigas: campos que não existirem (ex: sem
    "edit_plan" salvo) simplesmente vêm como None, sem quebrar.
    """
    analysis_file = Path(analysis_path)
    if not analysis_file.exists():
        raise MontageError(f"Não encontrei o arquivo de análise em {analysis_path}.")

    analysis = json.loads(analysis_file.read_text(encoding="utf-8"))
    top_moments = select_moments_automatically(analysis["moments"], max_moments=max_candidates)

    candidates = []
    for m in top_moments:
        candidates.append({
            "clip_id": m["clip_id"],
            "score": m["score"],
            "start_seconds": m["start_seconds"],
            "end_seconds": m["end_seconds"],
            "context_start_seconds": m["context_start_seconds"],
            "transcript_excerpt": m.get("transcript_excerpt", ""),
            "phrases": group_words_into_phrases(m.get("transcript_words", [])),
            "edit_plan": m.get("edit_plan"),  # só existe se já foi renderizado/persistido antes
            "breakdown": m.get("breakdown"),
        })
    return candidates


def render_single_clip(
    analysis_path: str,
    clip_id: str,
    start_override: float | None = None,
    end_override: float | None = None,
    orientation: str = "vertical",
    burn_captions: bool = True,
    subtitle_style: str = DEFAULT_SUBTITLE_STYLE,
    preset: str = DEFAULT_PRESET,
    layout: str = DEFAULT_LAYOUT,
    ai_title_config: dict | None = None,
    output_dir: str = "data/clips",
) -> dict:
    """
    Renderiza (ou re-renderiza) UM ÚNICO momento sob demanda, com ajustes
    manuais de início/fim, layout e preset — usado pela tela de revisão, pra
    não precisar reprocessar o vídeo inteiro (transcrição/detecção) só
    porque o usuário mudou o corte de um clip específico.

    Reaproveita o mesmo Edit Plan já gerado antes (se existir), sem chamar a
    IA de novo. Retorna {"video_path", "thumbnail_path", "duration_seconds"}.
    """
    analysis_file = Path(analysis_path)
    if not analysis_file.exists():
        raise MontageError(f"Não encontrei o arquivo de análise em {analysis_path}.")

    analysis = json.loads(analysis_file.read_text(encoding="utf-8"))
    video_path = analysis["video_path"]
    if not Path(video_path).exists():
        raise MontageError(f"O vídeo original ({video_path}) não foi encontrado.")

    moment = next((m for m in analysis["moments"] if m["clip_id"] == clip_id), None)
    if moment is None:
        raise MontageError(f"Momento {clip_id} não encontrado nessa análise.")

    # segurança: nunca deixa o usuário pedir um intervalo maluco (ex: fora do
    # vídeo, ou invertido) — limita a uma folga razoável em torno do momento
    # originalmente detectado, em vez de aceitar qualquer valor às cegas
    original_start = moment["context_start_seconds"]
    original_end = moment["end_seconds"]
    safety_margin = 30.0
    min_allowed = max(0.0, original_start - safety_margin)
    max_allowed = original_end + safety_margin

    start = start_override if start_override is not None else original_start
    end = end_override if end_override is not None else original_end
    start = max(min_allowed, min(start, max_allowed - 1.0))
    end = max(start + 1.0, min(end, max_allowed))

    output_dir_path = Path(output_dir)
    output_dir_path.mkdir(parents=True, exist_ok=True)

    clip_path = output_dir_path / f"{clip_id}_edited.mp4"
    cut_reframe_and_caption(
        video_path, moment, orientation, str(clip_path),
        burn_captions=burn_captions, srt_dir=str(output_dir_path),
        subtitle_style=subtitle_style, dynamic_zoom=False, trim_dead_air=False,
        auto_face_crop=False, edit_plan=moment.get("edit_plan"), preset=preset,
        layout=layout, start_override=start, end_override=end,
    )

    thumb_path = output_dir_path / f"{clip_id}_edited.jpg"
    thumb_text = get_thumbnail_text(moment.get("transcript_excerpt", ""), ai_title_config)
    # BUGFIX: usar moment["start_seconds"] direto podia cair FORA do clip novo
    # quando o usuário arrasta o início/fim bem longe do momento detectado
    # originalmente — trava o timestamp da thumbnail dentro de [start, end]
    thumb_timestamp = moment["start_seconds"]
    if not (start <= thumb_timestamp <= end):
        thumb_timestamp = (start + end) / 2
    extract_thumbnail(video_path, thumb_timestamp, str(thumb_path), text=thumb_text)

    return {
        "video_path": str(clip_path),
        "thumbnail_path": str(thumb_path),
        "duration_seconds": round(end - start, 1),
    }


def main():
    parser = argparse.ArgumentParser(description="Monta um clip final com os melhores momentos do VOD")
    parser.add_argument("--analysis", default="data/cache/analysis.json")
    parser.add_argument("--manual", action="store_true")
    parser.add_argument("--score-threshold", type=float, default=65.0)
    parser.add_argument("--max-duration", type=float, default=90.0)
    parser.add_argument("--max-moments", type=int, default=6)
    parser.add_argument("--platform", choices=list(PLATFORM_DURATION_PRESETS.keys()), default=None)
    parser.add_argument("--orientation", choices=["vertical", "horizontal"], default="vertical")
    parser.add_argument("--min-transition", type=float, default=0.15)
    parser.add_argument("--max-transition", type=float, default=0.8)
    parser.add_argument("--no-captions", action="store_true")
    parser.add_argument("--subtitle-style", choices=list(SUBTITLE_STYLES.keys()), default=DEFAULT_SUBTITLE_STYLE)
    parser.add_argument("--dynamic-zoom", action="store_true", help="EXPERIMENTAL: zoom lento durante o clip")
    parser.add_argument("--trim-dead-air", action="store_true", help="EXPERIMENTAL: remove silêncio interno")
    parser.add_argument("--auto-face-crop", action="store_true", help="EXPERIMENTAL: segue rosto/webcam no corte vertical")
    parser.add_argument("--preset", choices=list(EDIT_PRESETS.keys()), default=DEFAULT_PRESET, help="Clean (discreto) ou Impact (zoom + destaque, requer Edit Plan)")
    parser.add_argument("--output-dir", default="data/clips")
    args = parser.parse_args()

    try:
        pipeline_config = load_config()
        ai_title_config = pipeline_config.get("ai_title", {})
        edit_plan_config = pipeline_config.get("edit_plan", {})

        output_path, thumbnail_path, edit_plan, _duration = run_montage(
            analysis_path=args.analysis,
            auto=not args.manual,
            max_moments=args.max_moments,
            score_threshold=args.score_threshold,
            max_duration=args.max_duration,
            platform=args.platform,
            orientation=args.orientation,
            min_transition=args.min_transition,
            max_transition=args.max_transition,
            burn_captions=not args.no_captions,
            subtitle_style=args.subtitle_style,
            dynamic_zoom=args.dynamic_zoom,
            trim_dead_air=args.trim_dead_air,
            auto_face_crop=args.auto_face_crop,
            ai_title_config=ai_title_config,
            edit_plan_config=edit_plan_config,
            preset=args.preset,
            output_dir=args.output_dir,
        )
    except MontageError as e:
        print(f"\nErro: {e}")
        sys.exit(1)

    if output_path is None:
        print("\nNenhum momento com qualidade suficiente foi encontrado nesse vídeo. Nenhuma montagem foi gerada.")
        sys.exit(0)

    if edit_plan:
        print(f"\nPlano editorial do melhor momento ({edit_plan['clip_type']}): {edit_plan['explanation']}")
    print(f"\nPronto! Montagem final salva em: {output_path}")
    print(f"Thumbnail salvo em: {thumbnail_path}")


if __name__ == "__main__":
    main()