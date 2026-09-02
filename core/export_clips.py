"""
Corta os momentos candidatos individualmente (sem juntar em montagem) em
arquivos .mp4 reais, já com legenda queimada, thumbnail, e as melhorias mais
recentes (zoom dinâmico, corte de silêncio, seguir rosto, título por IA).

Uso:
    python core/export_clips.py --top 5
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.thumbnail import extract_thumbnail, get_thumbnail_text
from core.montage import cut_reframe_and_caption, MontageError, SUBTITLE_STYLES, DEFAULT_SUBTITLE_STYLE
from core.pipeline import load_config


def main():
    parser = argparse.ArgumentParser(description="Exporta os top N momentos candidatos como clipes .mp4 reais")
    parser.add_argument("--analysis", default="data/cache/analysis.json")
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--orientation", choices=["vertical", "horizontal"], default="vertical")
    parser.add_argument("--subtitle-style", choices=list(SUBTITLE_STYLES.keys()), default=DEFAULT_SUBTITLE_STYLE)
    parser.add_argument("--no-captions", action="store_true")
    parser.add_argument("--dynamic-zoom", action="store_true", help="EXPERIMENTAL: zoom lento durante o clip")
    parser.add_argument("--trim-dead-air", action="store_true", help="EXPERIMENTAL: remove silêncio interno")
    parser.add_argument("--auto-face-crop", action="store_true", help="EXPERIMENTAL: segue rosto/webcam no corte vertical")
    parser.add_argument("--output-dir", default="data/clips")
    args = parser.parse_args()

    analysis_path = Path(args.analysis)
    if not analysis_path.exists():
        print(f"Erro: {analysis_path} não encontrado. Rode primeiro core/pipeline.py.")
        sys.exit(1)

    config = load_config()
    ai_title_config = config.get("ai_title", {})

    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    video_path = analysis["video_path"]
    moments = analysis["moments"][: args.top]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Exportando {len(moments)} clipes de {video_path}...\n")
    try:
        for i, m in enumerate(moments, start=1):
            output_path = output_dir / f"{m['clip_id']}.mp4"
            thumbnail_path = output_dir / f"{m['clip_id']}.jpg"
            print(f"  [{i}/{len(moments)}] {m['clip_id']} (score {m['score']}) -> {output_path}")
            cut_reframe_and_caption(
                video_path, m, args.orientation, str(output_path),
                burn_captions=not args.no_captions, srt_dir=str(output_dir),
                subtitle_style=args.subtitle_style, dynamic_zoom=args.dynamic_zoom,
                trim_dead_air=args.trim_dead_air, auto_face_crop=args.auto_face_crop,
            )
            thumb_text = get_thumbnail_text(m.get("transcript_excerpt", ""), ai_title_config)
            extract_thumbnail(video_path, m["start_seconds"], str(thumbnail_path), text=thumb_text)
    except MontageError as e:
        print(f"\nErro: {e}")
        sys.exit(1)

    print(f"\nPronto! Os clipes e thumbnails estão em {output_dir}/")


if __name__ == "__main__":
    main()
