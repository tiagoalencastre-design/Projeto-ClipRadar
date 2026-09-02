"""
Processa TODOS os vídeos de uma pasta de uma vez (análise + montagem), com
todas as melhorias mais recentes (modo automático, zoom, corte de silêncio,
seguir rosto, título por IA) — em vez de rodar um por um manualmente.

Uso:
    python core/batch.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pipeline import load_config, run_pipeline, default_output_path, PipelineError
from core.montage import run_montage, MontageError, PLATFORM_DURATION_PRESETS, DEFAULT_PLATFORM, DEFAULT_SUBTITLE_STYLE


def process_all_videos(
    vods_dir: str = "data/vods",
    platform: str | None = None,
    orientation: str = "vertical",
    burn_captions: bool = True,
    subtitle_style: str = DEFAULT_SUBTITLE_STYLE,
) -> dict:
    config = load_config()
    ai_title_config = config.get("ai_title", {})
    videos = sorted(Path(vods_dir).glob("*.mp4"))

    summary = {"sucesso": [], "sem_momentos": [], "erro": []}

    if not videos:
        print(f"Nenhum vídeo .mp4 encontrado em {vods_dir}/")
        return summary

    print(f"Encontrados {len(videos)} vídeos. Processando um por um...\n")

    for i, video_path in enumerate(videos, start=1):
        print(f"[{i}/{len(videos)}] {video_path.name}")
        try:
            analysis_path = default_output_path(str(video_path))
            run_pipeline(str(video_path), config, analysis_path)

            output_video, thumbnail, _edit_plan = run_montage(
                analysis_path=analysis_path,
                auto=True,
                platform=platform,
                orientation=orientation,
                burn_captions=burn_captions,
                subtitle_style=subtitle_style,
                dynamic_zoom=True,
                trim_dead_air=True,
                auto_face_crop=True,
                ai_title_config=ai_title_config,
            )

            if output_video is None:
                print(f"    -> nenhum momento com qualidade suficiente foi encontrado")
                summary["sem_momentos"].append(video_path.name)
            else:
                print(f"    -> montagem salva em {output_video}")
                summary["sucesso"].append(video_path.name)

        except (PipelineError, MontageError) as e:
            print(f"    -> ERRO: {e}")
            summary["erro"].append((video_path.name, str(e)))
        except Exception as e:
            print(f"    -> ERRO inesperado: {e}")
            summary["erro"].append((video_path.name, str(e)))

    return summary


def main():
    parser = argparse.ArgumentParser(description="Processa todos os vídeos de uma pasta de uma vez")
    parser.add_argument("--vods-dir", default="data/vods")
    parser.add_argument("--platform", choices=list(PLATFORM_DURATION_PRESETS.keys()), default=DEFAULT_PLATFORM)
    parser.add_argument("--orientation", choices=["vertical", "horizontal"], default="vertical")
    parser.add_argument("--subtitle-style", default=DEFAULT_SUBTITLE_STYLE)
    parser.add_argument("--no-captions", action="store_true")
    args = parser.parse_args()

    summary = process_all_videos(
        vods_dir=args.vods_dir,
        platform=args.platform,
        orientation=args.orientation,
        burn_captions=not args.no_captions,
        subtitle_style=args.subtitle_style,
    )

    print("\n" + "=" * 50)
    print(f"Resumo: {len(summary['sucesso'])} concluídos, "
          f"{len(summary['sem_momentos'])} sem momentos bons o suficiente, "
          f"{len(summary['erro'])} com erro")
    if summary["erro"]:
        print("\nVídeos com erro:")
        for name, reason in summary["erro"]:
            print(f"  - {name}: {reason}")


if __name__ == "__main__":
    main()
