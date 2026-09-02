"""
Gera legendas ANIMADAS (palavra por palavra, estilo "karaokê" — a palavra
sendo falada no momento fica destacada) usando o formato .ass (Advanced
SubStation Alpha), que o filtro subtitles do FFmpeg entende nativamente.

Nota honesta: a cor de destaque no karaokê ASS depende de como o libass
interpreta Primary/Secondary — pode ser que a primeira versão renderize com
as cores "trocadas". Se isso acontecer, é só inverter PRIMARY e SECONDARY no
preset correspondente abaixo.
"""
from __future__ import annotations


def format_ass_timestamp(seconds: float) -> str:
    cs_total = int(round(max(seconds, 0) * 100))
    hours, cs_total = divmod(cs_total, 360_000)
    minutes, cs_total = divmod(cs_total, 6_000)
    secs, cs = divmod(cs_total, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


STYLE_PRESETS = {
    "classic": {
        "font": "Arial Black",
        "primary": "&H00FFFFFF",
        "secondary": "&H0000D7FF",
        "outline_color": "&H00000000",
        "back_color": "&H00000000",
        "border_style": 1,
        "outline": 4,
        "shadow": 2,
        "alignment": 2,
        "margin_v_ratio": 0.10,
    },
    "bold_yellow": {
        "font": "Arial Black",
        "primary": "&H0000FFFF",
        "secondary": "&H00FFFFFF",
        "outline_color": "&H00000000",
        "back_color": "&H00000000",
        "border_style": 1,
        "outline": 5,
        "shadow": 2,
        "alignment": 2,
        "margin_v_ratio": 0.11,
    },
    "minimal_top": {
        "font": "Arial",
        "primary": "&H00FFFFFF",
        "secondary": "&H00CCCCCC",
        "outline_color": "&H00000000",
        "back_color": "&H00000000",
        "border_style": 1,
        "outline": 2,
        "shadow": 0,
        "alignment": 8,
        "margin_v_ratio": 0.05,
    },
    "boxed": {
        "font": "Arial",
        "primary": "&H00FFFFFF",
        "secondary": "&H0000D7FF",
        "outline_color": "&H00000000",
        "back_color": "&H80000000",
        "border_style": 3,
        "outline": 0,
        "shadow": 0,
        "alignment": 2,
        "margin_v_ratio": 0.10,
    },
}
DEFAULT_STYLE = "classic"


def build_ass_karaoke(
    words: list[dict],
    window_start: float,
    window_end: float,
    style: str = DEFAULT_STYLE,
    play_res: tuple[int, int] = (1080, 1920),
    words_per_line: int = 4,
    highlight_words: list[str] | None = None,
) -> str:
    """
    highlight_words: palavras que devem receber destaque extra (cor diferente
    + negrito), além do efeito de karaokê normal — vem do plano editorial
    (core/edit_plan.py) quando disponível. A comparação ignora maiúsculas e
    pontuação simples.
    """
    preset = STYLE_PRESETS.get(style, STYLE_PRESETS[DEFAULT_STYLE])
    play_res_x, play_res_y = play_res
    font_size = max(int(play_res_x * 0.06), 20)
    margin_v = max(int(play_res_y * preset["margin_v_ratio"]), 10)

    highlight_set = {w.lower().strip(".,!?;:\"'") for w in (highlight_words or [])}
    # cor de destaque: usa a "secondary" do preset (já pensada pra chamar
    # atenção) pra pintar a palavra-chave inteira, não só durante o karaokê
    highlight_color = preset["secondary"]

    style_line = (
        f"Style: Default,{preset['font']},{font_size},"
        f"{preset['primary']},{preset['secondary']},{preset['outline_color']},{preset['back_color']},"
        f"-1,0,0,0,100,100,0,0,"
        f"{preset['border_style']},{preset['outline']},{preset['shadow']},"
        f"{preset['alignment']},40,40,{margin_v},1"
    )

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"{style_line}\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    relevant_words = [
        w for w in words
        if w["end"] > window_start and w["start"] < window_end
    ]

    events = []
    for i in range(0, len(relevant_words), words_per_line):
        chunk = relevant_words[i:i + words_per_line]
        if not chunk:
            continue

        line_start = max(chunk[0]["start"], window_start) - window_start
        line_end = min(chunk[-1]["end"], window_end) - window_start
        if line_end <= line_start:
            continue

        karaoke_parts = []
        for w in chunk:
            w_start = max(w["start"], window_start)
            w_end = min(w["end"], window_end)
            duration_cs = max(int(round((w_end - w_start) * 100)), 1)
            word_text = w["word"].strip()
            if not word_text:
                continue

            clean_word = word_text.lower().strip(".,!?;:\"'")
            if highlight_set and clean_word in highlight_set:
                # destaque extra: cor diferente + negrito durante essa palavra,
                # depois volta pro normal (\r reseta os overrides do estilo)
                karaoke_parts.append(
                    f"{{\\k{duration_cs}\\c{highlight_color}\\b1}}{word_text}{{\\r}}"
                )
            else:
                karaoke_parts.append(f"{{\\k{duration_cs}}}{word_text}")

        if not karaoke_parts:
            continue

        text = " ".join(karaoke_parts)
        events.append(
            f"Dialogue: 0,{format_ass_timestamp(line_start)},{format_ass_timestamp(line_end)},Default,,0,0,0,,{text}"
        )

    return header + "\n".join(events) + "\n"