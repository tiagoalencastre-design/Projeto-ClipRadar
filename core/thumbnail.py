"""
Extrai um frame do vídeo e transforma num thumbnail mais chamativo:
contraste/saturação realçados + texto de destaque por cima (título gerado
por IA quando configurado, ou extraído da fala como método antigo).
"""
from __future__ import annotations

import os
import re
import subprocess

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "arialbd.ttf",
    "DejaVuSans-Bold.ttf",
]


def extract_frame(video_path: str, timestamp_seconds: float, output_path: str) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(timestamp_seconds),
        "-i", video_path,
        "-frames:v", "1",
        "-q:v", "2",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg falhou ao extrair frame de {output_path}:\n{result.stderr[-1000:]}")


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for candidate in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def derive_thumbnail_text(transcript_excerpt: str, max_words: int = 6) -> str | None:
    if not transcript_excerpt:
        return None

    match = re.split(r"[.!?]", transcript_excerpt.strip())
    first_sentence = match[0].strip() if match else transcript_excerpt.strip()

    words = first_sentence.split()[:max_words]
    if not words:
        return None
    return " ".join(words).upper()


def get_thumbnail_text(transcript_excerpt: str, ai_title_config: dict | None = None) -> str | None:
    ai_title_config = ai_title_config or {}
    if ai_title_config.get("enabled") and ai_title_config.get("api_key"):
        from core.ai_title import generate_ai_title
        ai_title = generate_ai_title(
            transcript_excerpt,
            api_key=ai_title_config["api_key"],
            model=ai_title_config.get("model", "gpt-4o-mini"),
        )
        if ai_title:
            return ai_title

    return derive_thumbnail_text(transcript_excerpt)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    words = text.split()
    lines = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:2]


def create_attractive_thumbnail(frame_path: str, text: str | None, output_path: str) -> None:
    img = Image.open(frame_path).convert("RGB")

    img = ImageEnhance.Contrast(img).enhance(1.15)
    img = ImageEnhance.Color(img).enhance(1.3)
    img = ImageEnhance.Brightness(img).enhance(1.05)
    img = ImageEnhance.Sharpness(img).enhance(1.2)

    if text:
        width, height = img.size
        img_rgba = img.convert("RGBA")

        band_height = int(height * 0.30)
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        for y in range(band_height):
            alpha = int(160 * (y / band_height))
            overlay_draw.line(
                [(0, height - band_height + y), (width, height - band_height + y)],
                fill=(0, 0, 0, alpha),
            )
        img_rgba = Image.alpha_composite(img_rgba, overlay)
        img = img_rgba.convert("RGB")

        draw = ImageDraw.Draw(img)
        font_size = int(width * 0.075)
        font = _load_font(font_size)

        max_text_width = int(width * 0.9)
        lines = _wrap_text(text, font, max_text_width, draw)

        line_height = int(font_size * 1.15)
        y_start = height - int(band_height * 0.75)

        for i, line in enumerate(lines):
            line_width = draw.textlength(line, font=font)
            x = (width - line_width) / 2
            y = y_start + i * line_height
            stroke_width = max(int(font_size * 0.06), 2)
            draw.text((x, y), line, font=font, fill="white", stroke_width=stroke_width, stroke_fill="black")

    img.save(output_path, quality=92)


def extract_thumbnail(video_path: str, timestamp_seconds: float, output_path: str, text: str | None = None) -> None:
    raw_frame_path = output_path.replace(".jpg", "_raw.jpg")
    extract_frame(video_path, timestamp_seconds, raw_frame_path)
    create_attractive_thumbnail(raw_frame_path, text, output_path)

    if os.path.exists(raw_frame_path):
        os.remove(raw_frame_path)